from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AgriSeason(models.Model):
    _name = 'mdv.agri.season'
    _description = 'Growing Season'
    _order = 'date_start desc'

    name = fields.Char(required=True)
    date_start = fields.Date('Start', required=True)
    date_end = fields.Date('End', required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    plan_ids = fields.One2many('mdv.agri.crop.plan', 'season_id', string='Crop Plans')
    plan_count = fields.Integer(compute='_compute_plan_count')

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for season in self:
            if season.date_end < season.date_start:
                raise ValidationError(_('The season end date must be after its start date.'))

    def _compute_plan_count(self):
        for season in self:
            season.plan_count = len(season.plan_ids)

    @api.model
    def _season_for_date(self, date, company=None):
        company = company or self.env.company
        return self.search([('date_start', '<=', date), ('date_end', '>=', date),
                            ('company_id', 'in', (company.id, False))], limit=1)
