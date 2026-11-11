from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

ACTIVITY_TYPES = [
    ('land_prep', 'Land Preparation'),
    ('sowing', 'Sowing / Planting'),
    ('irrigation', 'Irrigation'),
    ('fertilizer', 'Fertiliser'),
    ('spraying', 'Spraying'),
    ('weeding', 'Weeding'),
    ('harvest', 'Harvest'),
    ('other', 'Other'),
]


class AgriCrop(models.Model):
    _name = 'mdv.agri.crop'
    _description = 'Crop'
    _inherit = ['mail.thread', 'mdv.agri.unit.mixin']
    _order = 'name'

    name = fields.Char(required=True, translate=True, tracking=True)
    code = fields.Char()
    scientific_name = fields.Char()
    category = fields.Selection([
        ('cereal', 'Cereal / Grain'), ('legume', 'Legume / Pulse'), ('oilseed', 'Oilseed'),
        ('vegetable', 'Vegetable'), ('fruit', 'Fruit'), ('fodder', 'Fodder / Forage'),
        ('fiber', 'Fibre'), ('beverage', 'Tea / Coffee / Cocoa'), ('other', 'Other'),
    ], default='cereal', required=True)
    image = fields.Image(max_width=512, max_height=512)
    product_id = fields.Many2one(
        'product.product', 'Harvest Product',
        help='Product received into stock (with a lot) when this crop is harvested and sold to customers.')
    yield_uom_id = fields.Many2one('uom.uom', 'Yield Unit', related='product_id.uom_id')
    growing_days = fields.Integer('Days to Harvest', default=120)
    expected_yield_per_ha = fields.Float('Expected Yield per ha', digits=(16, 2))
    expected_yield_per_acre = fields.Float('Expected Yield per acre', compute='_compute_yield_per_acre', inverse='_inverse_yield_per_acre', digits=(16, 2))
    base_temperature_c = fields.Float('GDD Base (C)', default=10.0,
                                      help='Base temperature used for growing degree days.')
    base_temperature_f = fields.Float('GDD Base (F)', compute='_compute_base_temperature_f', inverse='_inverse_base_temperature_f')
    season_ids = fields.Many2many('mdv.agri.season', string='Typical Seasons')
    variety_ids = fields.One2many('mdv.agri.crop.variety', 'crop_id', string='Varieties')
    template_line_ids = fields.One2many('mdv.agri.crop.template', 'crop_id', string='Activity Template')
    pest_ids = fields.Many2many('mdv.agri.pest', string='Known Pests and Diseases')
    plan_ids = fields.One2many('mdv.agri.crop.plan', 'crop_id')
    plan_count = fields.Integer(compute='_compute_plan_count')
    active = fields.Boolean(default=True)
    color = fields.Integer()
    notes = fields.Html()

    @api.depends('expected_yield_per_ha')
    def _compute_yield_per_acre(self):
        for crop in self:
            crop.expected_yield_per_acre = crop.expected_yield_per_ha / 2.4710538

    def _inverse_yield_per_acre(self):
        for crop in self:
            crop.expected_yield_per_ha = crop.expected_yield_per_acre * 2.4710538

    @api.depends('base_temperature_c')
    def _compute_base_temperature_f(self):
        for crop in self:
            crop.base_temperature_f = crop.base_temperature_c * 9 / 5 + 32

    def _inverse_base_temperature_f(self):
        for crop in self:
            crop.base_temperature_c = (crop.base_temperature_f - 32) * 5 / 9

    @api.constrains('growing_days', 'expected_yield_per_ha')
    def _check_values(self):
        for crop in self:
            if crop.growing_days < 0 or crop.expected_yield_per_ha < 0:
                raise ValidationError(_('Days to harvest and expected yield cannot be negative.'))

    def _compute_plan_count(self):
        for crop in self:
            crop.plan_count = len(crop.plan_ids)

    def action_open_plans(self):
        action = self.env['ir.actions.act_window']._for_xml_id('mdv_agriculture_suite.action_agri_crop_plan')
        action['domain'] = [('crop_id', '=', self.id)]
        action['context'] = {'default_crop_id': self.id}
        return action


class AgriCropVariety(models.Model):
    _name = 'mdv.agri.crop.variety'
    _description = 'Crop Variety'
    _inherit = ['mdv.agri.unit.mixin']
    _order = 'crop_id, name'

    name = fields.Char(required=True)
    crop_id = fields.Many2one('mdv.agri.crop', required=True, ondelete='cascade')
    growing_days = fields.Integer('Days to Harvest')
    expected_yield_per_ha = fields.Float('Expected Yield per ha', digits=(16, 2))
    expected_yield_per_acre = fields.Float('Expected Yield per acre', compute='_compute_yield_per_acre', inverse='_inverse_yield_per_acre', digits=(16, 2))
    seed_product_id = fields.Many2one('product.product', 'Seed Product')
    seed_rate_per_ha = fields.Float('Seed Rate per ha')
    seed_rate_per_acre = fields.Float('Seed Rate per acre', compute='_compute_seed_rate_per_acre', inverse='_inverse_seed_rate_per_acre')
    traits = fields.Char()
    active = fields.Boolean(default=True)

    @api.depends('expected_yield_per_ha')
    def _compute_yield_per_acre(self):
        for variety in self:
            variety.expected_yield_per_acre = variety.expected_yield_per_ha / 2.4710538

    def _inverse_yield_per_acre(self):
        for variety in self:
            variety.expected_yield_per_ha = variety.expected_yield_per_acre * 2.4710538

    @api.depends('seed_rate_per_ha')
    def _compute_seed_rate_per_acre(self):
        for variety in self:
            variety.seed_rate_per_acre = variety.seed_rate_per_ha / 2.4710538

    def _inverse_seed_rate_per_acre(self):
        for variety in self:
            variety.seed_rate_per_ha = variety.seed_rate_per_acre * 2.4710538

    @api.depends('name', 'crop_id.name')
    def _compute_display_name(self):
        for variety in self:
            variety.display_name = '%s - %s' % (variety.crop_id.name, variety.name) if variety.crop_id else variety.name


class AgriCropTemplate(models.Model):
    _name = 'mdv.agri.crop.template'
    _description = 'Crop Activity Template'
    _inherit = ['mdv.agri.unit.mixin']
    _order = 'crop_id, day_offset, sequence'

    crop_id = fields.Many2one('mdv.agri.crop', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    activity_type = fields.Selection(ACTIVITY_TYPES, required=True, default='other')
    day_offset = fields.Integer('Day (from sowing)', help='Negative values are before sowing.')
    product_id = fields.Many2one('product.product', 'Material', domain=[('type', '=', 'consu')])
    qty_per_ha = fields.Float('Material per ha')
    qty_per_acre = fields.Float('Material per acre', compute='_compute_qty_per_acre', inverse='_inverse_qty_per_acre')
    labour_hours_per_ha = fields.Float('Labour h per ha')
    labour_hours_per_acre = fields.Float('Labour h per acre', compute='_compute_labour_hours_per_acre', inverse='_inverse_labour_hours_per_acre')
    machine_hours_per_ha = fields.Float('Machine h per ha')
    machine_hours_per_acre = fields.Float('Machine h per acre', compute='_compute_machine_hours_per_acre', inverse='_inverse_machine_hours_per_acre')

    @api.depends('qty_per_ha')
    def _compute_qty_per_acre(self):
        for line in self:
            line.qty_per_acre = line.qty_per_ha / 2.4710538

    def _inverse_qty_per_acre(self):
        for line in self:
            line.qty_per_ha = line.qty_per_acre * 2.4710538

    @api.depends('labour_hours_per_ha')
    def _compute_labour_hours_per_acre(self):
        for line in self:
            line.labour_hours_per_acre = line.labour_hours_per_ha / 2.4710538

    def _inverse_labour_hours_per_acre(self):
        for line in self:
            line.labour_hours_per_ha = line.labour_hours_per_acre * 2.4710538

    @api.depends('machine_hours_per_ha')
    def _compute_machine_hours_per_acre(self):
        for line in self:
            line.machine_hours_per_acre = line.machine_hours_per_ha / 2.4710538

    def _inverse_machine_hours_per_acre(self):
        for line in self:
            line.machine_hours_per_ha = line.machine_hours_per_acre * 2.4710538
