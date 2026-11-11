from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AgriHarvest(models.Model):
    _name = 'mdv.agri.harvest'
    _description = 'Harvest'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.stock.mixin', 'mdv.agri.unit.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda self: _('New'))
    state = fields.Selection([('draft', 'Draft'), ('done', 'Received'), ('cancelled', 'Cancelled')],
                             default='draft', required=True, tracking=True, copy=False)
    plan_id = fields.Many2one('mdv.agri.crop.plan', required=True, ondelete='restrict', index=True,
                              check_company=True, domain="[('state', 'in', ('confirmed', 'growing', 'harvested'))]")
    field_id = fields.Many2one(related='plan_id.field_id', store=True)
    farm_id = fields.Many2one(related='plan_id.farm_id', store=True)
    crop_id = fields.Many2one(related='plan_id.crop_id', store=True)
    season_id = fields.Many2one(related='plan_id.season_id', store=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    product_id = fields.Many2one('product.product', required=True, compute='_compute_product_id', store=True,
                                 readonly=False, precompute=True)
    uom_id = fields.Many2one(related='product_id.uom_id')
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    quantity = fields.Float(required=True, digits=(16, 2), tracking=True)
    grade_id = fields.Many2one('mdv.agri.quality.grade', 'Quality Grade', tracking=True)
    moisture_pct = fields.Float('Moisture (%)', digits=(5, 2))
    area_harvested_ha = fields.Float('Area Harvested (ha)', digits=(16, 2))
    area_harvested_acre = fields.Float('Area Harvested (acres)', compute='_compute_area_harvested_acre', inverse='_inverse_area_harvested_acre', digits=(16, 2))
    yield_per_ha = fields.Float(compute='_compute_yield_per_ha', store=True, digits=(16, 2), aggregator='avg')
    yield_per_acre = fields.Float('Yield per acre', compute='_compute_yield_per_acre', digits=(16, 2), aggregator='avg')
    lot_name = fields.Char('Lot Number', copy=False, help='Leave empty to number the lot automatically.')
    lot_id = fields.Many2one('stock.lot', 'Lot', copy=False, readonly=True)
    location_dest_id = fields.Many2one('stock.location', 'Store In', compute='_compute_location_dest_id',
                                       store=True, readonly=False, domain="[('usage', '=', 'internal')]")
    move_id = fields.Many2one('stock.move', readonly=True, copy=False)
    sale_line_ids = fields.One2many('sale.order.line', 'mdv_harvest_id', string='Sales Lines')
    sold_qty = fields.Float(compute='_compute_sold_qty', digits=(16, 2))
    available_qty = fields.Float('Unsold', compute='_compute_sold_qty', digits=(16, 2))
    user_id = fields.Many2one('res.users', 'Recorded By', default=lambda self: self.env.user)
    notes = fields.Text()

    @api.depends('area_harvested_ha')
    def _compute_area_harvested_acre(self):
        for harvest in self:
            harvest.area_harvested_acre = harvest.area_harvested_ha * 2.4710538

    def _inverse_area_harvested_acre(self):
        for harvest in self:
            harvest.area_harvested_ha = harvest.area_harvested_acre / 2.4710538

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mdv.agri.harvest') or _('New')
        return super().create(vals_list)

    @api.depends('plan_id')
    def _compute_product_id(self):
        for harvest in self:
            if not harvest.product_id:
                harvest.product_id = harvest.plan_id.crop_id.product_id

    @api.depends('plan_id')
    def _compute_location_dest_id(self):
        for harvest in self:
            if not harvest.location_dest_id:
                harvest.location_dest_id = harvest.plan_id.farm_id._get_consumption_location() \
                    if harvest.plan_id.farm_id else False

    @api.depends('quantity', 'area_harvested_ha', 'plan_id.area_ha')
    def _compute_yield_per_ha(self):
        for harvest in self:
            area = harvest.area_harvested_ha or harvest.plan_id.area_ha
            harvest.yield_per_ha = harvest.quantity / area if area else 0.0

    @api.depends('yield_per_ha')
    def _compute_yield_per_acre(self):
        for harvest in self:
            harvest.yield_per_acre = harvest.yield_per_ha / 2.4710538

    @api.depends('sale_line_ids.product_uom_qty', 'sale_line_ids.state', 'quantity')
    def _compute_sold_qty(self):
        for harvest in self:
            harvest.sold_qty = sum(harvest.sale_line_ids.filtered(lambda sl: sl.state != 'cancel')
                                   .mapped('product_uom_qty'))
            harvest.available_qty = harvest.quantity - harvest.sold_qty

    @api.constrains('quantity', 'moisture_pct')
    def _check_quantity(self):
        for harvest in self:
            if harvest.quantity <= 0:
                raise ValidationError(_('The harvested quantity must be positive.'))
            if not 0 <= harvest.moisture_pct <= 100:
                raise ValidationError(_('Moisture must be a percentage between 0 and 100.'))

    def action_validate(self):
        for harvest in self:
            if harvest.state != 'draft':
                raise UserError(_('Only draft harvests can be validated.'))
            if harvest.plan_id.state not in ('confirmed', 'growing', 'harvested'):
                raise UserError(_('Crop plan %s is not open for harvests.', harvest.plan_id.name))
            if not harvest.location_dest_id:
                raise UserError(_('Set the stock location the harvest is stored in.'))
            lot = harvest._create_lot()
            harvest.move_id = harvest._agri_receive(
                harvest.product_id, harvest.quantity, harvest.product_id.uom_id, harvest.location_dest_id,
                harvest.company_id, '%s / %s' % (harvest.plan_id.name, harvest.name), lot=lot)
            harvest.write({'state': 'done', 'lot_id': lot.id if lot else False})
            if harvest.plan_id.state == 'confirmed':
                harvest.plan_id.state = 'growing'
        return True

    def _create_lot(self):
        self.ensure_one()
        if self.product_id.tracking == 'none':
            return self.env['stock.lot']
        name = self.lot_name or '%s-%s-%s' % (
            (self.crop_id.code or self.crop_id.name or 'LOT')[:6].upper().replace(' ', ''),
            (self.field_id.code or self.field_id.name or '')[:6].upper().replace(' ', ''),
            self.name.split('/')[-1])
        return self.env['stock.lot'].sudo().create({
            'name': name,
            'product_id': self.product_id.id,
            'company_id': self.company_id.id,
            'mdv_harvest_id': self.id,
        })

    def action_reset(self):
        for harvest in self.filtered(lambda h: h.state == 'done'):
            if harvest.sale_line_ids.filtered(lambda sl: sl.state == 'sale'):
                raise UserError(_('Harvest %s is already sold.', harvest.name))
            harvest._agri_reverse(harvest.move_id, _('Undo %s', harvest.name))
            harvest.write({'state': 'draft', 'move_id': False})
        return True

    def action_cancel(self):
        if self.filtered(lambda h: h.state == 'done'):
            raise UserError(_('Reset a received harvest before cancelling it.'))
        self.write({'state': 'cancelled'})
        return True

    def action_create_sale_order(self):
        harvests = self.filtered(lambda h: h.state == 'done' and h.available_qty > 0)
        if not harvests:
            raise UserError(_('Select received harvests that still have unsold quantity.'))
        return {
            'type': 'ir.actions.act_window', 'name': _('Sell Harvest'), 'res_model': 'mdv.agri.harvest.sell.wizard',
            'view_mode': 'form', 'target': 'new',
            'context': {'default_harvest_ids': [(6, 0, harvests.ids)]},
        }

    def action_view_sale_orders(self):
        orders = self.sale_line_ids.order_id
        return {'type': 'ir.actions.act_window', 'name': _('Sales Orders'), 'res_model': 'sale.order',
                'view_mode': 'list,form', 'domain': [('id', 'in', orders.ids)]}

    def action_print(self):
        return self.env.ref('mdv_agriculture_suite.action_report_harvest').report_action(self)
