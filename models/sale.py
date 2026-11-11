from odoo import fields, models
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mdv_crop_request_id = fields.Many2one('mdv.agri.crop.request', 'Crop Request', index='btree_not_null',
                                          copy=False)

    def action_confirm(self):
        res = super().action_confirm()
        self.order_line._mdv_reserve_harvest_lots()
        return res


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    mdv_harvest_id = fields.Many2one('mdv.agri.harvest', 'Harvest', index='btree_not_null', copy=False)
    mdv_crop_plan_id = fields.Many2one('mdv.agri.crop.plan', 'Crop Plan', index='btree_not_null', copy=False)
    mdv_lot_id = fields.Many2one('stock.lot', 'Harvest Lot', copy=False)

    def _mdv_reserve_harvest_lots(self):
        """Reserve the delivery from the harvest lot the customer bought, not from any lot."""
        for line in self.filtered('mdv_lot_id'):
            for move in line.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')
                                               and m.location_id.usage == 'internal'):
                move._do_unreserve()
                taken = move._update_reserved_quantity(move.product_qty, move.location_id,
                                                       lot_id=line.mdv_lot_id, strict=False)
                if float_compare(taken, move.product_qty, precision_rounding=move.product_id.uom_id.rounding) < 0:
                    move._action_assign()
                move._recompute_state()
