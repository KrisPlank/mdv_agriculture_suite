from odoo import api, fields, models


class AgriRequestPlanWizard(models.TransientModel):
    _name = 'mdv.agri.request.plan.wizard'
    _description = 'Plan a Crop Request'

    request_id = fields.Many2one('mdv.agri.crop.request', required=True)
    crop_id = fields.Many2one(related='request_id.crop_id')
    field_id = fields.Many2one('mdv.agri.field', required=True)
    season_id = fields.Many2one('mdv.agri.season', required=True, compute='_compute_season_id', store=True,
                                readonly=False, precompute=True)
    sowing_date = fields.Date(required=True, default=fields.Date.context_today)

    @api.depends('sowing_date')
    def _compute_season_id(self):
        for wiz in self:
            wiz.season_id = wiz.season_id or self.env['mdv.agri.season']._season_for_date(wiz.sowing_date)

    def action_create(self):
        plan = self.request_id._create_plan(self.field_id, self.season_id, self.sowing_date)
        return {'type': 'ir.actions.act_window', 'res_model': 'mdv.agri.crop.plan', 'res_id': plan.id,
                'view_mode': 'form'}
