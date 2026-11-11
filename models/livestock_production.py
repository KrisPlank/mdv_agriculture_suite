from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AgriMilkLog(models.Model):
    _name = 'mdv.agri.milk.log'
    _description = 'Milk Yield'
    _inherit = ['mdv.agri.unit.mixin']
    _order = 'date desc, session, id desc'
    _check_company_auto = True

    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    session = fields.Selection([('am', 'Morning'), ('noon', 'Noon'), ('pm', 'Evening'), ('day', 'Whole Day')],
                               required=True, default='am')
    animal_id = fields.Many2one('mdv.agri.animal', ondelete='cascade', index=True, check_company=True,
                                domain="[('sex', '=', 'female'), ('status', '=', 'active')]")
    herd_id = fields.Many2one('mdv.agri.herd', compute='_compute_herd_id', store=True, readonly=False,
                              index=True, check_company=True)
    farm_id = fields.Many2one(related='herd_id.farm_id', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    quantity_l = fields.Float('Milk (L)', required=True, digits=(16, 2))
    quantity_us_gal = fields.Float('Milk (US gal)', compute='_compute_quantity_us_gal', inverse='_inverse_quantity_us_gal', digits=(16, 2))
    fat_pct = fields.Float('Fat (%)', digits=(5, 2), aggregator='avg')
    protein_pct = fields.Float('Protein (%)', digits=(5, 2), aggregator='avg')
    scc = fields.Integer('SCC (1000/ml)', aggregator='avg', help='Somatic cell count')
    in_withdrawal = fields.Boolean(compute='_compute_withdrawal', store=True)
    discarded = fields.Boolean(compute='_compute_withdrawal', store=True, readonly=False,
                               help='Not sent to the tank (withdrawal period, colostrum, quality).')
    posted = fields.Boolean('In Stock', readonly=True, copy=False)
    move_id = fields.Many2one('stock.move', readonly=True, copy=False)

    @api.depends('quantity_l')
    def _compute_quantity_us_gal(self):
        for log in self:
            log.quantity_us_gal = log.quantity_l * 0.264172052

    def _inverse_quantity_us_gal(self):
        for log in self:
            log.quantity_l = log.quantity_us_gal / 0.264172052

    @api.depends('animal_id')
    def _compute_herd_id(self):
        for log in self:
            log.herd_id = log.animal_id.herd_id or log.herd_id

    @api.depends('animal_id.treatment_ids.withdrawal_until', 'animal_id.treatment_ids.state', 'date')
    def _compute_withdrawal(self):
        for log in self:
            withdrawal = bool(log.animal_id and log.date and log.animal_id.is_in_withdrawal(log.date))
            log.in_withdrawal = withdrawal
            log.discarded = withdrawal or log.discarded

    @api.constrains('quantity_l', 'fat_pct', 'protein_pct', 'animal_id', 'herd_id', 'date', 'session')
    def _check_values(self):
        for log in self:
            if log.quantity_l < 0:
                raise ValidationError(_('Milk quantity cannot be negative.'))
            if not 0 <= log.fat_pct <= 100 or not 0 <= log.protein_pct <= 100:
                raise ValidationError(_('Fat and protein are percentages.'))
            if not log.animal_id and not log.herd_id:
                raise ValidationError(_('A milk record needs an animal or a herd.'))
            if log.animal_id and self.search_count([('id', '!=', log.id), ('animal_id', '=', log.animal_id.id),
                                                    ('date', '=', log.date), ('session', '=', log.session)]):
                raise ValidationError(_('%(animal)s already has a %(session)s milk record on %(date)s.',
                                        animal=log.animal_id.display_name,
                                        session=dict(self._fields['session'].selection)[log.session], date=log.date))

    def action_post_to_stock(self):
        """Receive the tank milk (non-discarded) into the farm stock, one move per farm and day."""
        logs = self.filtered(lambda l: not l.posted and not l.discarded)
        if not logs:
            raise UserError(_('Nothing to receive: the selected records are already in stock or discarded.'))
        groups = defaultdict(lambda: self.browse())
        for log in logs:
            if not log.farm_id:
                raise UserError(_('Milk record of %s has no herd/farm.', log.date))
            groups[(log.farm_id, log.date)] |= log
        Mixin = self.env['mdv.agri.stock.mixin']
        for (farm, date), group in groups.items():
            product = farm.company_id.mdv_agri_milk_product_id
            if not product:
                raise UserError(_('Set the milk product in the agriculture settings.'))
            move = Mixin._agri_receive(product, sum(group.mapped('quantity_l')), product.uom_id,
                                       farm._get_consumption_location(), farm.company_id,
                                       _('Milk %(farm)s %(date)s', farm=farm.name, date=date))
            group.write({'posted': True, 'move_id': move.id})
        return True


class AgriEggLog(models.Model):
    _name = 'mdv.agri.egg.log'
    _description = 'Egg Production'
    _order = 'date desc, id desc'

    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    herd_id = fields.Many2one('mdv.agri.herd', 'Flock', required=True, ondelete='cascade', index=True,
                              domain="[('is_flock', '=', True)]")
    farm_id = fields.Many2one(related='herd_id.farm_id', store=True)
    company_id = fields.Many2one(related='herd_id.company_id', store=True)
    eggs_collected = fields.Integer(required=True)
    eggs_broken = fields.Integer('Broken / Rejected')
    eggs_saleable = fields.Integer(compute='_compute_eggs', store=True)
    birds_count = fields.Integer('Birds', compute='_compute_birds', store=True, readonly=False)
    lay_rate_pct = fields.Float('Lay Rate (%)', compute='_compute_eggs', store=True, digits=(5, 1),
                                aggregator='avg')
    avg_egg_weight_g = fields.Float('Avg Egg Weight (g)', digits=(6, 1), aggregator='avg')
    posted = fields.Boolean('In Stock', readonly=True, copy=False)
    move_id = fields.Many2one('stock.move', readonly=True, copy=False)

    _herd_date_unique = models.Constraint('UNIQUE(herd_id, date)', 'Eggs are recorded once per flock and day.')

    @api.depends('herd_id')
    def _compute_birds(self):
        for log in self:
            log.birds_count = log.birds_count or log.herd_id.current_count

    @api.depends('eggs_collected', 'eggs_broken', 'birds_count')
    def _compute_eggs(self):
        for log in self:
            log.eggs_saleable = max(0, log.eggs_collected - log.eggs_broken)
            log.lay_rate_pct = log.eggs_collected / log.birds_count * 100.0 if log.birds_count else 0.0

    @api.constrains('eggs_collected', 'eggs_broken')
    def _check_eggs(self):
        for log in self:
            if log.eggs_collected < 0 or log.eggs_broken < 0 or log.eggs_broken > log.eggs_collected:
                raise ValidationError(_('Broken eggs cannot exceed the eggs collected.'))

    def action_post_to_stock(self):
        logs = self.filtered(lambda l: not l.posted and l.eggs_saleable)
        if not logs:
            raise UserError(_('Nothing to receive: the selected records are already in stock.'))
        Mixin = self.env['mdv.agri.stock.mixin']
        unit = self.env.ref('uom.product_uom_unit')
        for log in logs:
            product = log.company_id.mdv_agri_egg_product_id
            if not product:
                raise UserError(_('Set the egg product in the agriculture settings.'))
            move = Mixin._agri_receive(product, log.eggs_saleable, unit, log.farm_id._get_consumption_location(),
                                       log.company_id, _('Eggs %(flock)s %(date)s', flock=log.herd_id.name,
                                                         date=log.date))
            log.write({'posted': True, 'move_id': move.id})
        return True


class AgriFeedLog(models.Model):
    _name = 'mdv.agri.feed.log'
    _description = 'Feed Consumption'
    _inherit = ['mdv.agri.stock.mixin']
    _order = 'date desc, id desc'

    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    herd_id = fields.Many2one('mdv.agri.herd', required=True, ondelete='cascade', index=True)
    animal_id = fields.Many2one('mdv.agri.animal', domain="[('herd_id', '=', herd_id)]")
    farm_id = fields.Many2one(related='herd_id.farm_id', store=True)
    company_id = fields.Many2one(related='herd_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    product_id = fields.Many2one('product.product', 'Feed', required=True, domain=[('type', '=', 'consu')])
    quantity = fields.Float(required=True, digits='Product Unit')
    uom_id = fields.Many2one(related='product_id.uom_id')
    unit_cost = fields.Float(digits='Product Price', readonly=True)
    amount = fields.Monetary(readonly=True, currency_field='currency_id')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Consumed')], default='draft', required=True)
    from_ration = fields.Boolean(readonly=True)
    move_id = fields.Many2one('stock.move', readonly=True, copy=False)

    @api.constrains('quantity')
    def _check_quantity(self):
        for log in self:
            if log.quantity <= 0:
                raise ValidationError(_('The feed quantity must be positive.'))

    def action_done(self):
        CostLine = self.env['mdv.agri.cost.line']
        for log in self.filtered(lambda l: l.state == 'draft'):
            location = log.farm_id._get_consumption_location()
            move = log._agri_consume([(log.product_id, log.quantity, log.product_id.uom_id)], location,
                                     log.company_id, _('Feed %(herd)s %(date)s', herd=log.herd_id.name, date=log.date))
            unit_cost = log.product_id.standard_price
            log.write({'state': 'done', 'move_id': move[:1].id, 'unit_cost': unit_cost,
                       'amount': unit_cost * log.quantity})
            CostLine.create({
                'name': _('Feed: %s', log.product_id.display_name), 'date': log.date, 'cost_type': 'feed',
                'herd_id': log.herd_id.id, 'animal_id': log.animal_id.id, 'farm_id': log.farm_id.id,
                'company_id': log.company_id.id, 'product_id': log.product_id.id, 'quantity': log.quantity,
                'unit_label': log.product_id.uom_id.name, 'unit_cost': unit_cost, 'amount': unit_cost * log.quantity,
            })
        return True


class AgriMortality(models.Model):
    _name = 'mdv.agri.mortality'
    _description = 'Mortality'
    _order = 'date desc, id desc'

    date = fields.Date(required=True, default=fields.Date.context_today)
    herd_id = fields.Many2one('mdv.agri.herd', required=True, ondelete='cascade', index=True)
    animal_id = fields.Many2one('mdv.agri.animal', domain="[('herd_id', '=', herd_id), ('status', '=', 'active')]")
    farm_id = fields.Many2one(related='herd_id.farm_id', store=True)
    company_id = fields.Many2one(related='herd_id.company_id', store=True)
    count = fields.Integer('Head', required=True, default=1)
    cause = fields.Selection([
        ('disease', 'Disease'), ('injury', 'Injury'), ('predator', 'Predator'), ('weather', 'Heat / Cold Stress'),
        ('birth', 'Birth Complication'), ('culled', 'Culled'), ('unknown', 'Unknown'),
    ], required=True, default='unknown')
    notes = fields.Text()

    @api.constrains('count', 'animal_id')
    def _check_count(self):
        for rec in self:
            if rec.count <= 0:
                raise ValidationError(_('Mortality must be at least one head.'))
            if rec.animal_id and rec.count != 1:
                raise ValidationError(_('A mortality record for one animal counts one head.'))
            herd = rec.herd_id
            if herd.is_flock and herd.mortality_count + herd.sold_count > herd.initial_count:
                raise ValidationError(_('Mortality exceeds the head count of %s.', rec.herd_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records.filtered('animal_id'):
            rec.animal_id.status = 'culled' if rec.cause == 'culled' else 'dead'
        return records
