from odoo import fields, models


class AgriUnitMixin(models.AbstractModel):
    _name = 'mdv.agri.unit.mixin'
    _description = 'Agriculture Unit Preference'

    mdv_agri_imperial_units = fields.Boolean(compute='_compute_imperial_units')

    def _compute_imperial_units(self):
        for record in self:
            company = self.env.company
            for path in ('company_id', 'farm_id.company_id', 'plan_id.company_id',
                         'activity_id.company_id', 'scouting_id.company_id'):
                value = record
                for part in path.split('.'):
                    if part not in value._fields:
                        value = False
                        break
                    value = value[part] if value else value
                if value:
                    company = value
                    break
            record.mdv_agri_imperial_units = company.mdv_agri_imperial_units
