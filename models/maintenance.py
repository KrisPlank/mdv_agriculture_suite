from odoo import _, api, fields, models


class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    mdv_agri_is_farm_machine = fields.Boolean('Farm Machine')
    mdv_agri_hourly_rate = fields.Float('Cost per Hour', digits='Product Price')
    mdv_agri_service_hours = fields.Float(
        'Service Every (h)', help='Engine hours between services. A preventive maintenance request is created '
                                  'automatically when field activities reach this many hours since the last service.')
    mdv_agri_hours_total = fields.Float('Engine Hours Logged', compute='_compute_mdv_agri_hours')
    mdv_agri_hours_since_service = fields.Float('Hours Since Service', compute='_compute_mdv_agri_hours')
    mdv_agri_last_service_date = fields.Date('Last Service')
    mdv_agri_machine_line_ids = fields.One2many('mdv.agri.activity.machine', 'equipment_id')

    @api.depends('mdv_agri_machine_line_ids.hours', 'mdv_agri_machine_line_ids.state', 'mdv_agri_last_service_date')
    def _compute_mdv_agri_hours(self):
        for eq in self:
            done = eq.mdv_agri_machine_line_ids.filtered(lambda line: line.state == 'done')
            eq.mdv_agri_hours_total = sum(done.mapped('hours'))
            if eq.mdv_agri_last_service_date:
                done = done.filtered(lambda line: line.activity_id.date_done
                                     and line.activity_id.date_done > eq.mdv_agri_last_service_date)
            eq.mdv_agri_hours_since_service = sum(done.mapped('hours'))

    def _mdv_check_service_due(self):
        Request = self.env['maintenance.request'].sudo()
        for eq in self:
            if not eq.mdv_agri_service_hours or eq.mdv_agri_hours_since_service < eq.mdv_agri_service_hours:
                continue
            open_request = Request.search([('equipment_id', '=', eq.id), ('maintenance_type', '=', 'preventive'),
                                           ('stage_id.done', '=', False)], limit=1)
            if open_request:
                continue
            Request.create({
                'name': _('%(machine)s: %(hours)s h service', machine=eq.name, hours=eq.mdv_agri_service_hours),
                'equipment_id': eq.id,
                'maintenance_type': 'preventive',
                'company_id': eq.company_id.id or self.env.company.id,
                'description': _('Created by field activities: %s engine hours since the last service.',
                                 round(eq.mdv_agri_hours_since_service, 1)),
            })


class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    def write(self, vals):
        res = super().write(vals)
        if 'stage_id' in vals:
            for req in self.filtered(lambda r: r.stage_id.done and r.equipment_id.mdv_agri_service_hours):
                req.equipment_id.sudo().mdv_agri_last_service_date = fields.Date.context_today(req)
        return res
