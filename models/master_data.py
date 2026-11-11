from odoo import api, fields, models


class AgriSoilType(models.Model):
    _name = 'mdv.agri.soil.type'
    _description = 'Soil Type'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    texture = fields.Selection([
        ('sand', 'Sandy'), ('loam', 'Loam'), ('clay', 'Clay'), ('silt', 'Silt'),
        ('peat', 'Peat'), ('chalk', 'Chalky'),
    ])
    drainage = fields.Selection([('poor', 'Poor'), ('moderate', 'Moderate'), ('good', 'Good')])
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)


class AgriQualityGrade(models.Model):
    _name = 'mdv.agri.quality.grade'
    _description = 'Harvest Quality Grade'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    price_factor = fields.Float(
        default=1.0, help='Multiplier applied to the product sales price when harvest lots of this grade are sold.')
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('UNIQUE(code)', 'The grade code must be unique.')


class AgriPest(models.Model):
    _name = 'mdv.agri.pest'
    _description = 'Pest, Disease or Weed'
    _order = 'pest_type, name'

    name = fields.Char(required=True, translate=True)
    pest_type = fields.Selection([
        ('insect', 'Insect Pest'), ('disease', 'Disease'), ('weed', 'Weed'),
        ('deficiency', 'Nutrient Deficiency'), ('other', 'Other'),
    ], required=True, default='insect')
    scientific_name = fields.Char()
    crop_ids = fields.Many2many('mdv.agri.crop', string='Affected Crops')
    symptoms = fields.Text(translate=True)
    threshold = fields.Char('Action Threshold', help='Economic threshold that triggers a treatment.')
    recommendation = fields.Text('Recommended Treatment', translate=True)
    treatment_line_ids = fields.One2many('mdv.agri.pest.treatment', 'pest_id', string='Treatment Products')
    image = fields.Image(max_width=1024, max_height=1024)
    active = fields.Boolean(default=True)


class AgriPestTreatment(models.Model):
    _name = 'mdv.agri.pest.treatment'
    _description = 'Recommended Treatment Product'

    pest_id = fields.Many2one('mdv.agri.pest', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, domain=[('type', '=', 'consu')])
    rate_per_ha = fields.Float('Rate per ha', required=True, default=1.0)
    uom_id = fields.Many2one(related='product_id.uom_id')
    note = fields.Char()


class AgriAnimalSpecies(models.Model):
    _name = 'mdv.agri.animal.species'
    _description = 'Animal Species'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    kind = fields.Selection([
        ('cattle', 'Cattle'), ('poultry', 'Poultry'), ('goat', 'Goat'), ('sheep', 'Sheep'),
        ('pig', 'Pig'), ('other', 'Other'),
    ], required=True, default='cattle')
    gestation_days = fields.Integer(help='Gestation or incubation length used to forecast the birth date.')
    produces_milk = fields.Boolean()
    produces_eggs = fields.Boolean()
    breed_ids = fields.One2many('mdv.agri.animal.breed', 'species_id', string='Breeds')
    active = fields.Boolean(default=True)

    @api.onchange('kind')
    def _onchange_kind(self):
        defaults = {'cattle': 283, 'goat': 150, 'sheep': 147, 'pig': 114, 'poultry': 21}
        if self.kind in defaults and not self.gestation_days:
            self.gestation_days = defaults[self.kind]
        self.produces_eggs = self.kind == 'poultry'


class AgriAnimalBreed(models.Model):
    _name = 'mdv.agri.animal.breed'
    _description = 'Animal Breed'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    species_id = fields.Many2one('mdv.agri.animal.species', required=True, ondelete='cascade')
    purpose = fields.Selection([('dairy', 'Dairy'), ('meat', 'Meat'), ('dual', 'Dual Purpose'),
                                ('layer', 'Layer'), ('broiler', 'Broiler'), ('wool', 'Wool')])
    active = fields.Boolean(default=True)
