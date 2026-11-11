from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class AgriHarvestSellWizard(models.TransientModel):
    _name = 'mdv.agri.harvest.sell.wizard'
    _description = 'Sell Harvest Lots'

    partner_id = fields.Many2one('res.partner', 'Customer', required=True)
    harvest_ids = fields.Many2many('mdv.agri.harvest')
    line_ids = fields.One2many('mdv.agri.harvest.sell.line', 'wizard_id', compute='_compute_line_ids',
                               store=True, readonly=False)

    @api.depends('harvest_ids')
    def _compute_line_ids(self):
        for wiz in self:
            commands = [(5, 0, 0)]
            for harvest in wiz.harvest_ids.filtered(lambda h: h.state == 'done' and h.available_qty > 0):
                factor = harvest.grade_id.price_factor or 1.0
                commands.append((0, 0, {'harvest_id': harvest.id, 'quantity': harvest.available_qty,
                                        'price_unit': harvest.product_id.lst_price * factor}))
            wiz.line_ids = commands

    def action_create(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Nothing to sell.'))
        order_lines = []
        for line in self.line_ids:
            harvest = line.harvest_id
            if float_compare(line.quantity, harvest.available_qty, precision_digits=2) > 0:
                raise UserError(_('Only %(qty)s left to sell from %(harvest)s.', qty=harvest.available_qty,
                                  harvest=harvest.name))
            if line.quantity <= 0:
                continue
            order_lines.append((0, 0, {
                'product_id': harvest.product_id.id, 'product_uom_qty': line.quantity, 'price_unit': line.price_unit,
                'mdv_harvest_id': harvest.id, 'mdv_crop_plan_id': harvest.plan_id.id,
                'mdv_lot_id': harvest.lot_id.id,
                'name': '%s - %s%s' % (harvest.product_id.display_name, _('Lot %s', harvest.lot_id.name)
                                       if harvest.lot_id else harvest.name,
                                       (' - %s' % harvest.grade_id.name) if harvest.grade_id else ''),
            }))
        if not order_lines:
            raise UserError(_('Nothing to sell.'))
        company = self.line_ids.harvest_id.company_id[:1]
        warehouse = self.line_ids.harvest_id.farm_id.warehouse_id[:1]
        vals = {'partner_id': self.partner_id.id, 'company_id': company.id, 'order_line': order_lines,
                'origin': ', '.join(self.line_ids.harvest_id.mapped('name'))}
        if warehouse:
            vals['warehouse_id'] = warehouse.id
        order = self.env['sale.order'].create(vals)
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': order.id, 'view_mode': 'form'}


class AgriHarvestSellLine(models.TransientModel):
    _name = 'mdv.agri.harvest.sell.line'
    _description = 'Sell Harvest Line'

    wizard_id = fields.Many2one('mdv.agri.harvest.sell.wizard', required=True, ondelete='cascade')
    harvest_id = fields.Many2one('mdv.agri.harvest', required=True)
    lot_id = fields.Many2one(related='harvest_id.lot_id')
    grade_id = fields.Many2one(related='harvest_id.grade_id')
    available_qty = fields.Float(related='harvest_id.available_qty')
    quantity = fields.Float(digits=(16, 2))
    price_unit = fields.Float(digits='Product Price')
