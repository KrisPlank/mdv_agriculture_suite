from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

HERD_TYPES = [
    ('dairy', 'Dairy Herd'), ('beef', 'Beef Herd'), ('layers', 'Layer Flock'), ('broilers', 'Broiler Flock'),
    ('breeders', 'Breeder Flock'), ('small_ruminant', 'Goats / Sheep'), ('pigs', 'Pigs'), ('other', 'Other'),
]


class AgriHerd(models.Model):
    _name = 'mdv.agri.herd'
    _description = 'Herd or Flock'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.stock.mixin', 'mdv.agri.unit.mixin']
    _order = 'farm_id, name'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    color = fields.Integer()
    farm_id = fields.Many2one('mdv.agri.farm', required=True, ondelete='restrict', check_company=True, index=True)
    company_id = fields.Many2one(related='farm_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    species_id = fields.Many2one('mdv.agri.animal.species', required=True)
    species_kind = fields.Selection(related='species_id.kind')
    breed_id = fields.Many2one('mdv.agri.animal.breed', domain="[('species_id', '=', species_id)]")
    herd_type = fields.Selection(HERD_TYPES, required=True, default='dairy')
    is_flock = fields.Boolean('Count by Head', help='Track the group by head count (poultry flocks, batches) '
                                                    'instead of individual animals.')
    shed = fields.Char('Shed / House')
    keeper_id = fields.Many2one('hr.employee', 'Keeper')
    placement_date = fields.Date('Placed On', help='Day the flock or batch was placed (day-old chicks).')
    initial_count = fields.Integer('Placed Head Count')
    sold_count = fields.Integer('Sold / Moved Out')
    age_weeks = fields.Integer('Flock Age (weeks)', compute='_compute_age_weeks')
    animal_ids = fields.One2many('mdv.agri.animal', 'herd_id', string='Animals')
    mortality_ids = fields.One2many('mdv.agri.mortality', 'herd_id', string='Mortality')
    milk_log_ids = fields.One2many('mdv.agri.milk.log', 'herd_id', string='Milk')
    egg_log_ids = fields.One2many('mdv.agri.egg.log', 'herd_id', string='Eggs')
    feed_log_ids = fields.One2many('mdv.agri.feed.log', 'herd_id', string='Feed')
    treatment_ids = fields.One2many('mdv.agri.vet.treatment', 'herd_id', string='Vet Treatments')
    ration_line_ids = fields.One2many('mdv.agri.feed.ration', 'herd_id', string='Daily Ration')
    cost_line_ids = fields.One2many('mdv.agri.cost.line', 'herd_id', string='Costs')
    analytic_account_id = fields.Many2one('account.analytic.account', check_company=True, copy=False)
    mortality_count = fields.Integer(compute='_compute_counts', store=True)
    current_count = fields.Integer('Head Count', compute='_compute_counts', store=True)
    mortality_pct = fields.Float('Mortality (%)', compute='_compute_counts', store=True, digits=(5, 2))
    milk_7d = fields.Float('Milk Last 7 Days (L)', compute='_compute_kpis', digits=(16, 1))
    milk_7d_us_gal = fields.Float('Milk Last 7 Days (US gal)', compute='_compute_milk_us_gal', digits=(16, 2))
    milk_per_head_day = fields.Float('Milk per Head per Day (L)', compute='_compute_kpis', digits=(16, 2))
    milk_per_head_day_us_gal = fields.Float('Milk per Head per Day (US gal)', compute='_compute_milk_us_gal', digits=(16, 3))
    eggs_7d = fields.Integer('Eggs Last 7 Days', compute='_compute_kpis')
    lay_rate_7d = fields.Float('Lay Rate 7 Days (%)', compute='_compute_kpis', digits=(5, 1))
    feed_cost = fields.Monetary('Feed Cost', compute='_compute_kpis')
    vet_cost = fields.Monetary('Vet Cost', compute='_compute_kpis')
    feed_per_litre = fields.Float('Feed kg per Litre (30 days)', compute='_compute_kpis', digits=(16, 3))
    feed_per_us_gallon = fields.Float('Feed lb per US gal (30 days)', compute='_compute_feed_per_us_gallon', digits=(16, 3))
    notes = fields.Html()

    @api.depends('milk_7d', 'milk_per_head_day')
    def _compute_milk_us_gal(self):
        for herd in self:
            herd.milk_7d_us_gal = herd.milk_7d * 0.264172052
            herd.milk_per_head_day_us_gal = herd.milk_per_head_day * 0.264172052

    @api.depends('feed_per_litre')
    def _compute_feed_per_us_gallon(self):
        for herd in self:
            herd.feed_per_us_gallon = herd.feed_per_litre * 2.2046226218 / 0.264172052

    @api.onchange('species_id')
    def _onchange_species_id(self):
        if self.species_id.kind == 'poultry':
            self.is_flock = True
            if self.herd_type not in ('layers', 'broilers', 'breeders'):
                self.herd_type = 'layers'
        elif self.species_id.kind in ('goat', 'sheep'):
            self.herd_type = 'small_ruminant'

    def _compute_age_weeks(self):
        today = fields.Date.context_today(self)
        for herd in self:
            herd.age_weeks = (today - herd.placement_date).days // 7 if herd.placement_date else 0

    @api.depends('is_flock', 'initial_count', 'sold_count', 'mortality_ids.count', 'animal_ids.status')
    def _compute_counts(self):
        for herd in self:
            dead = sum(herd.mortality_ids.mapped('count'))
            herd.mortality_count = dead
            if herd.is_flock:
                herd.current_count = max(0, herd.initial_count - dead - herd.sold_count)
                herd.mortality_pct = dead / herd.initial_count * 100.0 if herd.initial_count else 0.0
            else:
                herd.current_count = len(herd.animal_ids.filtered(lambda a: a.status == 'active'))
                total = len(herd.animal_ids)
                herd.mortality_pct = dead / total * 100.0 if total else 0.0

    def _compute_kpis(self):
        today = fields.Date.context_today(self)
        week = today - timedelta(days=6)
        month = today - timedelta(days=29)
        for herd in self:
            milk = herd.milk_log_ids.filtered(lambda m: week <= m.date <= today and not m.discarded)
            herd.milk_7d = sum(milk.mapped('quantity_l'))
            heads = herd.current_count or 0
            herd.milk_per_head_day = herd.milk_7d / (heads * 7) if heads else 0.0
            eggs = herd.egg_log_ids.filtered(lambda e: week <= e.date <= today)
            herd.eggs_7d = sum(eggs.mapped('eggs_collected'))
            bird_days = sum(eggs.mapped('birds_count'))
            herd.lay_rate_7d = herd.eggs_7d / bird_days * 100.0 if bird_days else 0.0
            costs = herd.cost_line_ids
            herd.feed_cost = sum(costs.filtered(lambda c: c.cost_type == 'feed').mapped('amount'))
            herd.vet_cost = sum(costs.filtered(lambda c: c.cost_type == 'vet').mapped('amount'))
            feed_30 = sum(herd.feed_log_ids.filtered(lambda f: f.state == 'done' and month <= f.date <= today)
                          .mapped('quantity'))
            milk_30 = sum(herd.milk_log_ids.filtered(lambda m: month <= m.date <= today and not m.discarded)
                          .mapped('quantity_l'))
            herd.feed_per_litre = feed_30 / milk_30 if milk_30 else 0.0

    def action_create_analytic_account(self):
        project_plan, _other = self.env['account.analytic.plan'].sudo()._get_all_plans()
        for herd in self.filtered(lambda h: not h.analytic_account_id):
            herd.analytic_account_id = self.env['account.analytic.account'].sudo().create({
                'name': '%s - %s' % (herd.farm_id.name, herd.name), 'plan_id': project_plan.id,
                'company_id': herd.company_id.id,
            })

    def action_record_daily_feed(self, date=None):
        """Create and consume today's feed from the ration table times the head count."""
        date = date or fields.Date.context_today(self)
        logs = self.env['mdv.agri.feed.log']
        for herd in self:
            if not herd.ration_line_ids:
                raise UserError(_('Herd %s has no daily ration.', herd.name))
            if not herd.current_count:
                raise UserError(_('Herd %s has no animals.', herd.name))
            if herd.feed_log_ids.filtered(lambda f: f.date == date and f.from_ration and f.state == 'done'):
                raise UserError(_('The ration of %(herd)s was already recorded for %(date)s.', herd=herd.name, date=date))
            new = logs.create([{
                'herd_id': herd.id, 'date': date, 'product_id': line.product_id.id,
                'quantity': round(line.qty_per_head * herd.current_count, 3), 'from_ration': True,
            } for line in herd.ration_line_ids])
            new.action_done()
            logs |= new
        return logs

    def _open(self, model, title):
        return {'type': 'ir.actions.act_window', 'name': title, 'res_model': model, 'view_mode': 'list,form',
                'domain': [('herd_id', '=', self.id)], 'context': {'default_herd_id': self.id}}

    def action_view_animals(self):
        return self._open('mdv.agri.animal', _('Animals'))

    def action_view_milk(self):
        return self._open('mdv.agri.milk.log', _('Milk'))

    def action_view_eggs(self):
        return self._open('mdv.agri.egg.log', _('Eggs'))

    def action_view_feed(self):
        return self._open('mdv.agri.feed.log', _('Feed'))

    def action_view_treatments(self):
        return self._open('mdv.agri.vet.treatment', _('Vet Treatments'))


class AgriFeedRation(models.Model):
    _name = 'mdv.agri.feed.ration'
    _description = 'Daily Feed Ration'

    herd_id = fields.Many2one('mdv.agri.herd', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', 'Feed', required=True, domain=[('type', '=', 'consu')])
    qty_per_head = fields.Float('Per Head per Day', required=True, digits=(16, 4))
    uom_id = fields.Many2one(related='product_id.uom_id')


class AgriAnimal(models.Model):
    _name = 'mdv.agri.animal'
    _description = 'Animal'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.unit.mixin']
    _order = 'tag'
    _rec_names_search = ['tag', 'name', 'rfid']
    _check_company_auto = True

    name = fields.Char(tracking=True)
    tag = fields.Char('Ear Tag', required=True, tracking=True)
    rfid = fields.Char('RFID / EID')
    image = fields.Image(max_width=1024, max_height=1024)
    species_id = fields.Many2one('mdv.agri.animal.species', required=True)
    breed_id = fields.Many2one('mdv.agri.animal.breed', domain="[('species_id', '=', species_id)]")
    sex = fields.Selection([('female', 'Female'), ('male', 'Male')], required=True, default='female')
    birth_date = fields.Date()
    age_months = fields.Integer('Age (months)', compute='_compute_age')
    herd_id = fields.Many2one('mdv.agri.herd', tracking=True, check_company=True, index=True)
    farm_id = fields.Many2one('mdv.agri.farm', compute='_compute_farm_id', store=True, readonly=False,
                              check_company=True, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    dam_id = fields.Many2one('mdv.agri.animal', 'Dam (Mother)', domain="[('sex', '=', 'female')]")
    sire_id = fields.Many2one('mdv.agri.animal', 'Sire (Father)', domain="[('sex', '=', 'male')]")
    offspring_ids = fields.One2many('mdv.agri.animal', 'dam_id', string='Offspring')
    status = fields.Selection([('active', 'Active'), ('sold', 'Sold'), ('dead', 'Dead'), ('culled', 'Culled')],
                              default='active', required=True, tracking=True)
    purpose = fields.Selection([('dairy', 'Dairy'), ('meat', 'Meat'), ('breeding', 'Breeding'),
                                ('draught', 'Draught'), ('wool', 'Wool')])
    lactation_status = fields.Selection([('lactating', 'Lactating'), ('dry', 'Dry'), ('none', 'Not in Milk')],
                                        default='none', tracking=True)
    last_birth_date = fields.Date('Last Calving / Kidding')
    days_in_milk = fields.Integer(compute='_compute_age')
    weight_log_ids = fields.One2many('mdv.agri.animal.weight', 'animal_id', string='Weights')
    weight_kg = fields.Float('Weight (kg)', compute='_compute_weight', store=True, digits=(16, 1))
    weight_lb = fields.Float('Weight (lb)', compute='_compute_weight_lb', digits=(16, 1))
    breeding_ids = fields.One2many('mdv.agri.breeding', 'animal_id', string='Breeding')
    treatment_ids = fields.One2many('mdv.agri.vet.treatment', 'animal_id', string='Vet Treatments')
    milk_log_ids = fields.One2many('mdv.agri.milk.log', 'animal_id', string='Milk')
    reproductive_status = fields.Selection([
        ('open', 'Open'), ('inseminated', 'Inseminated'), ('pregnant', 'Pregnant'),
    ], compute='_compute_reproduction', store=True)
    expected_birth_date = fields.Date(compute='_compute_reproduction', store=True)
    withdrawal_until = fields.Date('Withdrawal Until', compute='_compute_withdrawal', store=True,
                                   help='Milk and meat must not be sold until this date because of a treatment.')
    milk_7d = fields.Float('Milk Last 7 Days (L)', compute='_compute_milk', digits=(16, 1))
    milk_total = fields.Float('Milk Total (L)', compute='_compute_milk', digits=(16, 1))
    milk_7d_us_gal = fields.Float('Milk Last 7 Days (US gal)', compute='_compute_milk_us_gal', digits=(16, 2))
    milk_total_us_gal = fields.Float('Milk Total (US gal)', compute='_compute_milk_us_gal', digits=(16, 2))
    notes = fields.Html()
    color = fields.Integer(compute='_compute_color')

    _tag_company_unique = models.Constraint('UNIQUE(tag, company_id)', 'The ear tag must be unique per company.')

    @api.depends('tag', 'name')
    def _compute_display_name(self):
        for animal in self:
            animal.display_name = '%s - %s' % (animal.tag, animal.name) if animal.name else (animal.tag or '')

    @api.depends('herd_id')
    def _compute_farm_id(self):
        for animal in self:
            animal.farm_id = animal.herd_id.farm_id or animal.farm_id

    def _compute_age(self):
        today = fields.Date.context_today(self)
        for animal in self:
            animal.age_months = ((today.year - animal.birth_date.year) * 12 + today.month - animal.birth_date.month) \
                if animal.birth_date else 0
            animal.days_in_milk = (today - animal.last_birth_date).days \
                if animal.last_birth_date and animal.lactation_status == 'lactating' else 0

    @api.depends('status')
    def _compute_color(self):
        for animal in self:
            animal.color = {'active': 10, 'sold': 4, 'dead': 1, 'culled': 3}.get(animal.status, 0)

    @api.depends('weight_log_ids.weight_kg', 'weight_log_ids.date')
    def _compute_weight(self):
        for animal in self:
            animal.weight_kg = animal.weight_log_ids.sorted('date', reverse=True)[:1].weight_kg

    @api.depends('weight_kg')
    def _compute_weight_lb(self):
        for animal in self:
            animal.weight_lb = animal.weight_kg * 2.2046226218

    @api.depends('breeding_ids.state', 'breeding_ids.expected_birth_date')
    def _compute_reproduction(self):
        for animal in self:
            current = animal.breeding_ids.filtered(lambda b: b.state in ('inseminated', 'pregnant')) \
                .sorted('date', reverse=True)[:1]
            animal.reproductive_status = current.state or 'open'
            animal.expected_birth_date = current.expected_birth_date

    @api.depends('treatment_ids.withdrawal_until', 'treatment_ids.state')
    def _compute_withdrawal(self):
        for animal in self:
            dates = animal.treatment_ids.filtered(lambda t: t.state == 'done' and t.withdrawal_until) \
                .mapped('withdrawal_until')
            animal.withdrawal_until = max(dates) if dates else False

    def _compute_milk(self):
        today = fields.Date.context_today(self)
        week = today - timedelta(days=6)
        for animal in self:
            logs = animal.milk_log_ids.filtered(lambda m: not m.discarded)
            animal.milk_total = sum(logs.mapped('quantity_l'))
            animal.milk_7d = sum(logs.filtered(lambda m: week <= m.date <= today).mapped('quantity_l'))

    @api.depends('milk_7d', 'milk_total')
    def _compute_milk_us_gal(self):
        for animal in self:
            animal.milk_7d_us_gal = animal.milk_7d * 0.264172052
            animal.milk_total_us_gal = animal.milk_total * 0.264172052

    @api.constrains('dam_id', 'sire_id', 'species_id', 'birth_date')
    def _check_parents(self):
        for animal in self:
            if animal.dam_id and (animal.dam_id == animal or animal.dam_id.sex != 'female'):
                raise ValidationError(_('The dam of %s must be another, female animal.', animal.tag))
            if animal.sire_id and (animal.sire_id == animal or animal.sire_id.sex != 'male'):
                raise ValidationError(_('The sire of %s must be another, male animal.', animal.tag))
            for parent in (animal.dam_id | animal.sire_id):
                if parent.species_id != animal.species_id:
                    raise ValidationError(_('Parents of %s must be of the same species.', animal.tag))
            if animal.birth_date and animal.birth_date > fields.Date.context_today(animal):
                raise ValidationError(_('The birth date of %s is in the future.', animal.tag))

    def is_in_withdrawal(self, date):
        self.ensure_one()
        return any(t.state == 'done' and t.withdrawal_until and t.date <= date <= t.withdrawal_until
                   for t in self.treatment_ids)

    def action_view_offspring(self):
        return {'type': 'ir.actions.act_window', 'name': _('Offspring'), 'res_model': 'mdv.agri.animal',
                'view_mode': 'list,form', 'domain': ['|', ('dam_id', '=', self.id), ('sire_id', '=', self.id)]}


class AgriAnimalWeight(models.Model):
    _name = 'mdv.agri.animal.weight'
    _description = 'Animal Weight'
    _inherit = ['mdv.agri.unit.mixin']
    _order = 'date desc'

    animal_id = fields.Many2one('mdv.agri.animal', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='animal_id.company_id')
    date = fields.Date(required=True, default=fields.Date.context_today)
    weight_kg = fields.Float('Weight (kg)', required=True, digits=(16, 1))
    weight_lb = fields.Float('Weight (lb)', compute='_compute_weight_lb', inverse='_inverse_weight_lb', digits=(16, 1))
    daily_gain_kg = fields.Float('Daily Gain (kg)', compute='_compute_gain', digits=(16, 3))
    daily_gain_lb = fields.Float('Daily Gain (lb)', compute='_compute_daily_gain_lb', digits=(16, 3))

    @api.depends('weight_kg')
    def _compute_weight_lb(self):
        for record in self:
            record.weight_lb = record.weight_kg * 2.2046226218

    def _inverse_weight_lb(self):
        for record in self:
            record.weight_kg = record.weight_lb / 2.2046226218

    @api.depends('daily_gain_kg')
    def _compute_daily_gain_lb(self):
        for record in self:
            record.daily_gain_lb = record.daily_gain_kg * 2.2046226218

    @api.depends('weight_kg', 'date', 'animal_id.weight_log_ids')
    def _compute_gain(self):
        for rec in self:
            previous = rec.animal_id.weight_log_ids.filtered(lambda w: w.date < rec.date).sorted('date', reverse=True)[:1]
            days = (rec.date - previous.date).days if previous else 0
            rec.daily_gain_kg = (rec.weight_kg - previous.weight_kg) / days if days else 0.0


class AgriBreeding(models.Model):
    _name = 'mdv.agri.breeding'
    _description = 'Breeding / Insemination'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.stock.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda self: _('New'))
    animal_id = fields.Many2one('mdv.agri.animal', 'Female', required=True, ondelete='cascade', index=True,
                                domain="[('sex', '=', 'female'), ('status', '=', 'active')]")
    species_id = fields.Many2one(related='animal_id.species_id', store=True)
    herd_id = fields.Many2one(related='animal_id.herd_id', store=True)
    company_id = fields.Many2one(related='animal_id.company_id', store=True)
    date = fields.Date('Service Date', required=True, default=fields.Date.context_today, tracking=True)
    method = fields.Selection([('natural', 'Natural Service'), ('ai', 'Artificial Insemination'),
                               ('et', 'Embryo Transfer')], required=True, default='ai')
    sire_id = fields.Many2one('mdv.agri.animal', 'Sire', domain="[('sex', '=', 'male'), ('species_id', '=', species_id)]")
    semen_ref = fields.Char('Semen / Straw Ref')
    semen_product_id = fields.Many2one('product.product', 'Straw Product', domain=[('type', '=', 'consu')],
                                       help='Consumed from the farm stock when the service is recorded.')
    technician_id = fields.Many2one('res.partner', 'Technician / Vet')
    pregnancy_check_date = fields.Date(compute='_compute_dates', store=True, readonly=False)
    expected_birth_date = fields.Date(compute='_compute_dates', store=True, readonly=False)
    state = fields.Selection([
        ('inseminated', 'Inseminated'), ('pregnant', 'Pregnant'), ('open', 'Not Pregnant'),
        ('delivered', 'Delivered'), ('lost', 'Pregnancy Lost'),
    ], default='inseminated', required=True, tracking=True)
    birth_date = fields.Date('Birth Date', readonly=True)
    offspring_ids = fields.One2many('mdv.agri.animal', 'mdv_breeding_id', string='Offspring')
    offspring_count = fields.Integer(compute='_compute_offspring_count')
    move_id = fields.Many2one('stock.move', readonly=True)
    notes = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mdv.agri.breeding') or _('New')
        records = super().create(vals_list)
        for rec in records.filtered('semen_product_id'):
            location = rec.animal_id.farm_id._get_consumption_location() if rec.animal_id.farm_id else False
            if location:
                rec.move_id = rec._agri_consume([(rec.semen_product_id, 1.0, rec.semen_product_id.uom_id)],
                                                location, rec.company_id, rec.name)[:1]
        return records

    @api.depends('date', 'animal_id.species_id.gestation_days')
    def _compute_dates(self):
        for rec in self:
            gestation = rec.animal_id.species_id.gestation_days
            rec.expected_birth_date = rec.date + timedelta(days=gestation) if rec.date and gestation else False
            check_days = 7 if rec.animal_id.species_id.kind == 'poultry' else 35
            rec.pregnancy_check_date = rec.date + timedelta(days=check_days) if rec.date else False

    def _compute_offspring_count(self):
        for rec in self:
            rec.offspring_count = len(rec.offspring_ids)

    @api.constrains('animal_id', 'sire_id')
    def _check_animals(self):
        for rec in self:
            if rec.animal_id.sex != 'female':
                raise ValidationError(_('Breeding is recorded on the female.'))
            if rec.sire_id and (rec.sire_id.sex != 'male' or rec.sire_id.species_id != rec.animal_id.species_id):
                raise ValidationError(_('The sire must be a male of the same species.'))

    def action_confirm_pregnant(self):
        self.filtered(lambda b: b.state == 'inseminated').write({'state': 'pregnant'})
        return True

    def action_mark_open(self):
        self.filtered(lambda b: b.state == 'inseminated').write({'state': 'open'})
        return True

    def action_mark_lost(self):
        self.filtered(lambda b: b.state == 'pregnant').write({'state': 'lost'})
        return True

    def action_register_birth(self):
        self.ensure_one()
        if self.state not in ('inseminated', 'pregnant'):
            raise UserError(_('Only an active pregnancy can end in a birth.'))
        return {'type': 'ir.actions.act_window', 'name': _('Register Birth'), 'res_model': 'mdv.agri.birth.wizard',
                'view_mode': 'form', 'target': 'new', 'context': {'default_breeding_id': self.id}}

    def _register_birth(self, birth_date, offspring_vals):
        """offspring_vals: list of dicts with tag, sex, name, weight_kg."""
        self.ensure_one()
        Animal = self.env['mdv.agri.animal']
        dam = self.animal_id
        created = Animal
        for vals in offspring_vals:
            animal = Animal.create({
                'tag': vals['tag'], 'name': vals.get('name'), 'sex': vals.get('sex') or 'female',
                'species_id': dam.species_id.id, 'breed_id': dam.breed_id.id, 'birth_date': birth_date,
                'herd_id': dam.herd_id.id, 'farm_id': dam.farm_id.id, 'company_id': dam.company_id.id,
                'dam_id': dam.id, 'sire_id': self.sire_id.id, 'mdv_breeding_id': self.id,
                'weight_log_ids': [(0, 0, {'date': birth_date, 'weight_kg': vals['weight_kg']})]
                if vals.get('weight_kg') else [],
            })
            created |= animal
        self.write({'state': 'delivered', 'birth_date': birth_date})
        dam_vals = {'last_birth_date': birth_date}
        if dam.species_id.produces_milk:
            dam_vals['lactation_status'] = 'lactating'
        dam.write(dam_vals)
        return created

    @api.model
    def _cron_breeding_reminders(self):
        today = fields.Date.context_today(self)
        soon = today + timedelta(days=14)
        checks = self.search([('state', '=', 'inseminated'), ('pregnancy_check_date', '<=', today)])
        births = self.search([('state', '=', 'pregnant'), ('expected_birth_date', '<=', soon)])
        todo = self.env.ref('mail.mail_activity_data_todo')
        for rec in checks | births:
            summary = _('Pregnancy check due') if rec.state == 'inseminated' else _('Birth expected %s',
                                                                                    rec.expected_birth_date)
            if rec.activity_ids.filtered(lambda a: a.summary == summary):
                continue
            user = rec.herd_id.farm_id.manager_id or self.env.user
            rec.activity_schedule(activity_type_id=todo.id, summary=summary, user_id=user.id,
                                  date_deadline=rec.pregnancy_check_date if rec.state == 'inseminated'
                                  else rec.expected_birth_date)


class AgriAnimalBreeding(models.Model):
    _inherit = 'mdv.agri.animal'

    mdv_breeding_id = fields.Many2one('mdv.agri.breeding', 'Born From', readonly=True, index='btree_not_null')
