from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SEVERITY = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')]


class AgriScouting(models.Model):
    _name = 'mdv.agri.scouting'
    _description = 'Crop Scouting'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.unit.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda self: _('New'))
    state = fields.Selection([
        ('draft', 'Observed'), ('reviewed', 'Treatment Planned'), ('treated', 'Treated'), ('closed', 'Closed'),
    ], default='draft', required=True, tracking=True, copy=False)
    plan_id = fields.Many2one('mdv.agri.crop.plan', required=True, ondelete='cascade', index=True,
                              check_company=True, domain="[('state', 'in', ('confirmed', 'growing'))]")
    field_id = fields.Many2one(related='plan_id.field_id', store=True)
    farm_id = fields.Many2one(related='plan_id.farm_id', store=True)
    crop_id = fields.Many2one(related='plan_id.crop_id', store=True)
    season_id = fields.Many2one(related='plan_id.season_id', store=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    scout_id = fields.Many2one('res.users', 'Scout', default=lambda self: self.env.user)
    growth_stage = fields.Selection([
        ('emergence', 'Emergence'), ('vegetative', 'Vegetative'), ('flowering', 'Flowering'),
        ('fruiting', 'Fruit / Grain Fill'), ('maturity', 'Maturity'),
    ])
    pest_id = fields.Many2one('mdv.agri.pest', 'Pest / Disease', required=True, tracking=True)
    pest_type = fields.Selection(related='pest_id.pest_type', store=True)
    severity = fields.Selection(SEVERITY, required=True, default='low', tracking=True)
    incidence_pct = fields.Float('Plants Affected (%)', digits=(5, 1))
    affected_area_ha = fields.Float('Affected Area (ha)', digits=(16, 2))
    affected_area_acre = fields.Float('Affected Area (acres)', compute='_compute_affected_area_acre',
                                      inverse='_inverse_affected_area_acre', digits=(16, 2))
    latitude = fields.Float(digits=(10, 6))
    longitude = fields.Float(digits=(10, 6))
    observation = fields.Text()
    recommendation = fields.Text(compute='_compute_recommendation', store=True, readonly=False)
    photo_ids = fields.One2many('mdv.agri.scouting.photo', 'scouting_id', string='Photos')
    photo_count = fields.Integer(compute='_compute_photo_count')
    image_main = fields.Image(related='photo_ids.image', string='Main Photo')
    treatment_line_ids = fields.One2many('mdv.agri.scouting.treatment', 'scouting_id', string='Treatment',
                                         compute='_compute_treatment_lines', store=True, readonly=False)
    spray_activity_id = fields.Many2one('mdv.agri.activity', 'Spraying Activity', copy=False, readonly=True)
    weather_log_id = fields.Many2one('mdv.agri.weather.log', compute='_compute_weather')
    temp_max_c = fields.Float('Max Temp (C)', compute='_compute_weather')
    wind_max_kmh = fields.Float('Wind (km/h)', compute='_compute_weather')
    precipitation_mm = fields.Float('Rain (mm)', compute='_compute_weather')
    temp_max_f = fields.Float('Max Temp (F)', compute='_compute_weather_imperial')
    wind_max_mph = fields.Float('Wind (mph)', compute='_compute_weather_imperial')
    precipitation_in = fields.Float('Rain (in)', compute='_compute_weather_imperial')
    color = fields.Integer(compute='_compute_color')

    @api.depends('affected_area_ha')
    def _compute_affected_area_acre(self):
        for record in self:
            record.affected_area_acre = record.affected_area_ha * 2.4710538

    def _inverse_affected_area_acre(self):
        for record in self:
            record.affected_area_ha = record.affected_area_acre / 2.4710538

    @api.depends('temp_max_c', 'wind_max_kmh', 'precipitation_mm')
    def _compute_weather_imperial(self):
        for record in self:
            record.temp_max_f = record.temp_max_c * 9 / 5 + 32
            record.wind_max_mph = record.wind_max_kmh * 0.6213711922
            record.precipitation_in = record.precipitation_mm / 25.4

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mdv.agri.scouting') or _('New')
        records = super().create(vals_list)
        records._notify_critical()
        return records

    @api.constrains('incidence_pct', 'affected_area_ha')
    def _check_values(self):
        for rec in self:
            if not 0 <= rec.incidence_pct <= 100:
                raise ValidationError(_('Plants affected must be a percentage between 0 and 100.'))
            if rec.affected_area_ha < 0 or (rec.plan_id.area_ha and rec.affected_area_ha > rec.plan_id.area_ha + 0.005):
                raise ValidationError(_('The affected area must be between 0 and the planted area.'))

    @api.depends('severity')
    def _compute_color(self):
        colors = {'low': 10, 'medium': 3, 'high': 2, 'critical': 1}
        for rec in self:
            rec.color = colors.get(rec.severity, 0)

    def _compute_photo_count(self):
        for rec in self:
            rec.photo_count = len(rec.photo_ids)

    def _compute_weather(self):
        Weather = self.env['mdv.agri.weather.log']
        for rec in self:
            log = Weather.search([('farm_id', '=', rec.farm_id.id), ('date', '=', rec.date)], limit=1)
            rec.weather_log_id = log
            rec.temp_max_c = log.temp_max_c
            rec.wind_max_kmh = log.wind_max_kmh
            rec.precipitation_mm = log.precipitation_mm

    @api.depends('pest_id')
    def _compute_recommendation(self):
        for rec in self:
            rec.recommendation = rec.recommendation or rec.pest_id.recommendation

    @api.depends('pest_id', 'affected_area_ha')
    def _compute_treatment_lines(self):
        for rec in self:
            if rec.state != 'draft' or rec.spray_activity_id:
                rec.treatment_line_ids = rec.treatment_line_ids
                continue
            area = rec.affected_area_ha or rec.plan_id.area_ha
            commands = [(5, 0, 0)]
            for line in rec.pest_id.treatment_line_ids:
                commands.append((0, 0, {'product_id': line.product_id.id, 'rate_per_ha': line.rate_per_ha,
                                        'quantity': round(line.rate_per_ha * area, 3)}))
            rec.treatment_line_ids = commands

    def _notify_critical(self):
        for rec in self.filtered(lambda r: r.severity in ('high', 'critical')):
            user = rec.plan_id.responsible_id or rec.farm_id.manager_id
            if user:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_('%(severity)s %(pest)s on %(field)s', severity=dict(SEVERITY)[rec.severity],
                              pest=rec.pest_id.name, field=rec.field_id.name))

    def action_create_spray(self):
        """Turn the recommended treatment into a planned spraying activity on the crop plan."""
        self.ensure_one()
        if self.spray_activity_id:
            raise UserError(_('A spraying activity already exists for %s.', self.name))
        if not self.treatment_line_ids:
            raise UserError(_('Add at least one treatment product first.'))
        activity = self.env['mdv.agri.activity'].create({
            'name': _('Spray %(pest)s (%(ref)s)', pest=self.pest_id.name, ref=self.name),
            'plan_id': self.plan_id.id,
            'activity_type': 'spraying',
            'date_planned': fields.Date.context_today(self),
            'scouting_id': self.id,
            'notes': self.recommendation,
            'material_line_ids': [(0, 0, {'product_id': line.product_id.id, 'quantity': line.quantity,
                                          'uom_id': line.product_id.uom_id.id})
                                  for line in self.treatment_line_ids],
        })
        self.write({'spray_activity_id': activity.id, 'state': 'reviewed'})
        return {'type': 'ir.actions.act_window', 'res_model': 'mdv.agri.activity', 'res_id': activity.id,
                'view_mode': 'form'}

    def action_close(self):
        self.write({'state': 'closed'})
        return True

    def action_reopen(self):
        self.write({'state': 'draft'})
        return True

    def action_print(self):
        return self.env.ref('mdv_agriculture_suite.action_report_scouting').report_action(self)


class AgriScoutingPhoto(models.Model):
    _name = 'mdv.agri.scouting.photo'
    _description = 'Scouting Photo'
    _order = 'sequence, id'

    scouting_id = fields.Many2one('mdv.agri.scouting', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char('Caption')
    image = fields.Image(required=True, max_width=1600, max_height=1600)


class AgriScoutingTreatment(models.Model):
    _name = 'mdv.agri.scouting.treatment'
    _description = 'Scouting Treatment Line'
    _inherit = ['mdv.agri.unit.mixin']

    scouting_id = fields.Many2one('mdv.agri.scouting', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', required=True, domain=[('type', '=', 'consu')])
    rate_per_ha = fields.Float('Rate per ha', digits=(16, 3))
    rate_per_acre = fields.Float('Rate per acre', compute='_compute_rate_per_acre',
                                 inverse='_inverse_rate_per_acre', digits=(16, 3))
    quantity = fields.Float(required=True, digits='Product Unit')
    uom_id = fields.Many2one(related='product_id.uom_id')

    @api.depends('rate_per_ha')
    def _compute_rate_per_acre(self):
        for line in self:
            line.rate_per_acre = line.rate_per_ha / 2.4710538

    def _inverse_rate_per_acre(self):
        for line in self:
            line.rate_per_ha = line.rate_per_acre * 2.4710538
