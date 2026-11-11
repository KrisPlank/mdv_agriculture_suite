from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AgriVetTreatment(models.Model):
    _name = 'mdv.agri.vet.treatment'
    _description = 'Veterinary Treatment'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.stock.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda self: _('New'))
    treatment_type = fields.Selection([
        ('treatment', 'Treatment'), ('vaccination', 'Vaccination'), ('deworming', 'Deworming'),
        ('checkup', 'Check-up'), ('surgery', 'Surgery'),
    ], required=True, default='treatment', tracking=True)
    state = fields.Selection([('planned', 'Planned'), ('done', 'Done'), ('cancelled', 'Cancelled')],
                             default='planned', required=True, tracking=True, copy=False)
    animal_id = fields.Many2one('mdv.agri.animal', ondelete='cascade', index=True, check_company=True)
    herd_id = fields.Many2one('mdv.agri.herd', compute='_compute_herd_id', store=True, readonly=False,
                              ondelete='cascade', index=True, check_company=True)
    farm_id = fields.Many2one(related='herd_id.farm_id', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    symptoms = fields.Text()
    diagnosis = fields.Char(tracking=True)
    vet_partner_id = fields.Many2one('res.partner', 'Veterinarian')
    vet_fee = fields.Monetary(currency_field='currency_id')
    head_count = fields.Integer('Heads Treated', compute='_compute_head_count', store=True, readonly=False)
    medicine_line_ids = fields.One2many('mdv.agri.vet.medicine', 'treatment_id', string='Medicines', copy=True)
    withdrawal_days = fields.Integer('Withdrawal (days)', help='Days milk and meat must be withheld after treatment.')
    withdrawal_until = fields.Date(compute='_compute_withdrawal_until', store=True)
    quarantine = fields.Boolean()
    schedule_id = fields.Many2one('mdv.agri.vaccination.schedule', 'Vaccination Schedule', readonly=True)
    move_ids = fields.Many2many('stock.move', string='Stock Moves', readonly=True, copy=False)
    cost_line_ids = fields.One2many('mdv.agri.cost.line', 'mdv_treatment_id', string='Costs')
    total_cost = fields.Monetary(compute='_compute_total_cost', currency_field='currency_id')
    bill_id = fields.Many2one('account.move', 'Vendor Bill', readonly=True, copy=False)
    notes = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mdv.agri.vet.treatment') or _('New')
        return super().create(vals_list)

    @api.depends('animal_id')
    def _compute_herd_id(self):
        for rec in self:
            rec.herd_id = rec.animal_id.herd_id or rec.herd_id

    @api.depends('animal_id', 'herd_id.current_count')
    def _compute_head_count(self):
        for rec in self:
            if rec.state != 'done':
                rec.head_count = 1 if rec.animal_id else rec.herd_id.current_count
            else:
                rec.head_count = rec.head_count

    @api.depends('date', 'withdrawal_days', 'state')
    def _compute_withdrawal_until(self):
        for rec in self:
            rec.withdrawal_until = rec.date + timedelta(days=rec.withdrawal_days) \
                if rec.state == 'done' and rec.withdrawal_days else False

    @api.depends('cost_line_ids.amount')
    def _compute_total_cost(self):
        for rec in self:
            rec.total_cost = sum(rec.cost_line_ids.mapped('amount'))

    @api.constrains('animal_id', 'herd_id')
    def _check_target(self):
        for rec in self:
            if not rec.animal_id and not rec.herd_id:
                raise ValidationError(_('A treatment needs an animal or a herd.'))

    def action_done(self):
        for rec in self:
            if rec.state != 'planned':
                raise UserError(_('Only planned treatments can be completed.'))
            farm = rec.farm_id or rec.animal_id.farm_id
            moves = self.env['stock.move']
            lines = [(ml.product_id, ml.quantity, ml.product_id.uom_id) for ml in rec.medicine_line_ids]
            if lines:
                if not farm:
                    raise UserError(_('Set the herd or farm of %s to take medicines from stock.', rec.name))
                moves = rec._agri_consume(lines, farm._get_consumption_location(), rec.company_id, rec.name)
            base = {'date': rec.date, 'cost_type': 'vet', 'herd_id': rec.herd_id.id, 'animal_id': rec.animal_id.id,
                    'farm_id': farm.id if farm else False, 'company_id': rec.company_id.id,
                    'mdv_treatment_id': rec.id}
            vals_list = [dict(base, name=ml.product_id.display_name, product_id=ml.product_id.id,
                              quantity=ml.quantity, unit_label=ml.product_id.uom_id.name,
                              unit_cost=ml.product_id.standard_price,
                              amount=ml.quantity * ml.product_id.standard_price)
                         for ml in rec.medicine_line_ids]
            if rec.vet_fee:
                vals_list.append(dict(base, name=_('Vet fee %s', rec.name), quantity=1, unit_cost=rec.vet_fee,
                                      amount=rec.vet_fee))
            self.env['mdv.agri.cost.line'].create(vals_list)
            rec.write({'state': 'done'})
            rec.sudo().move_ids = [(6, 0, moves.ids)]
        return True

    def action_cancel(self):
        if self.filtered(lambda r: r.state == 'done'):
            raise UserError(_('Done treatments cannot be cancelled.'))
        self.write({'state': 'cancelled'})
        return True

    def action_create_bill(self):
        """One-click vendor bill for the vet fee, on the herd's analytic account when it has one."""
        self.ensure_one()
        if not self.vet_partner_id or not self.vet_fee:
            raise UserError(_('Set the veterinarian and the fee first.'))
        if self.bill_id:
            raise UserError(_('A bill already exists for %s.', self.name))
        line = {'name': _('Veterinary services %(ref)s %(dx)s', ref=self.name, dx=self.diagnosis or ''),
                'quantity': 1, 'price_unit': self.vet_fee}
        if self.herd_id.analytic_account_id:
            line['analytic_distribution'] = {str(self.herd_id.analytic_account_id.id): 100}
        self.bill_id = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.vet_partner_id.id, 'company_id': self.company_id.id,
            'invoice_date': self.date, 'ref': self.name, 'invoice_line_ids': [(0, 0, line)],
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.bill_id.id,
                'view_mode': 'form'}


class AgriVetMedicine(models.Model):
    _name = 'mdv.agri.vet.medicine'
    _description = 'Treatment Medicine'

    treatment_id = fields.Many2one('mdv.agri.vet.treatment', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', required=True, domain=[('type', '=', 'consu')])
    quantity = fields.Float(required=True, default=1.0, digits='Product Unit')
    uom_id = fields.Many2one(related='product_id.uom_id')
    dosage = fields.Char()


class AgriVaccinationSchedule(models.Model):
    _name = 'mdv.agri.vaccination.schedule'
    _description = 'Vaccination Schedule'
    _order = 'species_id, first_age_days'

    name = fields.Char('Vaccine / Programme', required=True)
    species_id = fields.Many2one('mdv.agri.animal.species', required=True)
    herd_type = fields.Selection(lambda self: self.env['mdv.agri.herd']._fields['herd_type'].selection,
                                 help='Leave empty for every herd of the species.')
    product_id = fields.Many2one('product.product', 'Vaccine Product', domain=[('type', '=', 'consu')])
    dose_per_head = fields.Float(default=1.0, digits=(16, 4))
    first_age_days = fields.Integer('First Dose at Age (days)', required=True)
    repeat_days = fields.Integer('Repeat Every (days)', help='0 = single dose.')
    withdrawal_days = fields.Integer('Withdrawal (days)')
    lead_days = fields.Integer('Plan Days Ahead', default=14)
    active = fields.Boolean(default=True)

    @api.constrains('first_age_days', 'repeat_days')
    def _check_days(self):
        for rec in self:
            if rec.first_age_days < 0 or rec.repeat_days < 0:
                raise ValidationError(_('Vaccination days cannot be negative.'))

    def _next_due(self, start_date, last_done):
        self.ensure_one()
        if last_done:
            return last_done + timedelta(days=self.repeat_days) if self.repeat_days else False
        return start_date + timedelta(days=self.first_age_days) if start_date else False

    def _generate_due(self, today=None):
        """Create planned vaccination treatments that fall due within the lead time."""
        today = today or fields.Date.context_today(self)
        Treatment = self.env['mdv.agri.vet.treatment']
        created = Treatment
        for sched in self:
            horizon = today + timedelta(days=sched.lead_days)
            herd_domain = [('species_id', '=', sched.species_id.id), ('active', '=', True)]
            if sched.herd_type:
                herd_domain.append(('herd_type', '=', sched.herd_type))
            herds = self.env['mdv.agri.herd'].search(herd_domain)
            targets = []
            for herd in herds.filtered('is_flock'):
                targets.append(('herd', herd, herd.placement_date))
            animals = self.env['mdv.agri.animal'].search([
                ('species_id', '=', sched.species_id.id), ('status', '=', 'active'),
                '|', ('herd_id', '=', False), ('herd_id', 'in', herds.filtered(lambda h: not h.is_flock).ids)])
            if sched.herd_type:
                animals = animals.filtered(lambda a: a.herd_id.herd_type == sched.herd_type)
            for animal in animals:
                targets.append(('animal', animal, animal.birth_date))
            for kind, target, start in targets:
                domain = [('schedule_id', '=', sched.id), (kind + '_id', '=', target.id)]
                if Treatment.search_count(domain + [('state', '=', 'planned')]):
                    continue
                last = Treatment.search(domain + [('state', '=', 'done')], order='date desc', limit=1)
                due = sched._next_due(start, last.date)
                if not due or due > horizon:
                    continue
                if not last and due < today - timedelta(days=max(sched.repeat_days, 30)):
                    # an old animal that never got this dose: plan it for today, not in the past
                    due = today
                herd = target if kind == 'herd' else target.herd_id
                heads = target.current_count if kind == 'herd' else 1
                created |= Treatment.create({
                    'treatment_type': 'vaccination', 'schedule_id': sched.id, 'date': due,
                    'animal_id': target.id if kind == 'animal' else False, 'herd_id': herd.id,
                    'company_id': (herd.company_id or target.company_id).id, 'diagnosis': sched.name,
                    'withdrawal_days': sched.withdrawal_days, 'head_count': heads,
                    'medicine_line_ids': [(0, 0, {'product_id': sched.product_id.id,
                                                  'quantity': round(sched.dose_per_head * heads, 4)})]
                    if sched.product_id else [],
                })
        return created

    @api.model
    def _cron_generate_vaccinations(self):
        return self.search([])._generate_due()


class AgriCostLineTreatment(models.Model):
    _inherit = 'mdv.agri.cost.line'

    mdv_treatment_id = fields.Many2one('mdv.agri.vet.treatment', ondelete='cascade', index='btree_not_null')
