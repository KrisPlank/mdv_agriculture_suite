from odoo import fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    mdv_harvest_id = fields.Many2one('mdv.agri.harvest', 'Harvest', index='btree_not_null', readonly=True)
    mdv_crop_plan_id = fields.Many2one(related='mdv_harvest_id.plan_id', string='Crop Plan', store=True)
    mdv_farm_id = fields.Many2one(related='mdv_harvest_id.farm_id', string='Farm', store=True)
    mdv_field_id = fields.Many2one(related='mdv_harvest_id.field_id', string='Field', store=True)
    mdv_season_id = fields.Many2one(related='mdv_harvest_id.season_id', string='Season', store=True)
    mdv_harvest_date = fields.Date(related='mdv_harvest_id.date', string='Harvest Date', store=True)
    mdv_grade_id = fields.Many2one(related='mdv_harvest_id.grade_id', string='Quality Grade', store=True)
    mdv_moisture_pct = fields.Float(related='mdv_harvest_id.moisture_pct', string='Moisture (%)')


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    mdv_crop_plan_id = fields.Many2one('mdv.agri.crop.plan', 'Crop Plan', index='btree_not_null', copy=False)
    mdv_crop_request_id = fields.Many2one('mdv.agri.crop.request', 'Crop Request', index='btree_not_null',
                                          copy=False)
