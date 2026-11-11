from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AgriBirthWizard(models.TransientModel):
    _name = 'mdv.agri.birth.wizard'
    _description = 'Register Birth'

    breeding_id = fields.Many2one('mdv.agri.breeding', required=True)
    dam_id = fields.Many2one(related='breeding_id.animal_id')
    birth_date = fields.Date(required=True, default=fields.Date.context_today)
    line_ids = fields.One2many('mdv.agri.birth.wizard.line', 'wizard_id', string='Offspring')

    def action_register(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Add at least one newborn.'))
        animals = self.breeding_id._register_birth(self.birth_date, [
            {'tag': line.tag, 'name': line.name, 'sex': line.sex, 'weight_kg': line.weight_kg}
            for line in self.line_ids])
        return {'type': 'ir.actions.act_window', 'name': _('Newborns'), 'res_model': 'mdv.agri.animal',
                'view_mode': 'list,form', 'domain': [('id', 'in', animals.ids)]}


class AgriBirthWizardLine(models.TransientModel):
    _name = 'mdv.agri.birth.wizard.line'
    _description = 'Newborn'

    wizard_id = fields.Many2one('mdv.agri.birth.wizard', required=True, ondelete='cascade')
    tag = fields.Char('Ear Tag', required=True)
    name = fields.Char()
    sex = fields.Selection([('female', 'Female'), ('male', 'Male')], required=True, default='female')
    weight_kg = fields.Float('Birth Weight (kg)')
