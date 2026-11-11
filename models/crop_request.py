from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AgriCropRequest(models.Model):
    _name = 'mdv.agri.crop.request'
    _description = 'Crop Request'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda self: _('New'))
    state = fields.Selection([
        ('new', 'New'), ('review', 'Under Review'), ('approved', 'Approved'), ('converted', 'In Production'),
        ('rejected', 'Rejected'), ('cancelled', 'Cancelled'),
    ], default='new', required=True, tracking=True, copy=False)
    request_type = fields.Selection([
        ('supply', 'Grow and Supply to Me'),
        ('grower', 'I Grow for You (Contract Grower)'),
        ('service', 'Farm My Land (Farming Service)'),
    ], required=True, default='supply', tracking=True)
    partner_id = fields.Many2one('res.partner', 'Customer / Grower', required=True, tracking=True, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', 'Handled By', tracking=True)
    crop_id = fields.Many2one('mdv.agri.crop', required=True, tracking=True)
    variety_id = fields.Many2one('mdv.agri.crop.variety', domain="[('crop_id', '=', crop_id)]")
    quantity = fields.Float(digits=(16, 2), tracking=True)
    uom_id = fields.Many2one(related='crop_id.yield_uom_id')
    area_ha = fields.Float('Area (ha)', digits=(16, 2))
    desired_date = fields.Date('Wanted By')
    price_unit = fields.Float('Agreed Price per Unit', digits='Product Price', tracking=True)
    land_location = fields.Char('Land Location')
    latitude = fields.Float(digits=(10, 6))
    longitude = fields.Float(digits=(10, 6))
    description = fields.Text()
    reject_reason = fields.Char()
    plan_id = fields.Many2one('mdv.agri.crop.plan', 'Crop Plan', readonly=True, copy=False)
    purchase_order_id = fields.Many2one('purchase.order', readonly=True, copy=False)
    sale_order_id = fields.Many2one('sale.order', 'Quotation', readonly=True, copy=False)
    source = fields.Selection([('backend', 'Back Office'), ('portal', 'Customer Portal'), ('website', 'Website')],
                              default='backend', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mdv.agri.crop.request') or _('New')
        records = super().create(vals_list)
        for rec in records:
            rec.message_subscribe(partner_ids=rec.partner_id.ids)
        return records

    @api.constrains('quantity', 'area_ha')
    def _check_amounts(self):
        for rec in self:
            if rec.quantity < 0 or rec.area_ha < 0:
                raise ValidationError(_('Quantity and area cannot be negative.'))
            if not rec.quantity and not rec.area_ha:
                raise ValidationError(_('Give a quantity or an area for the crop request.'))

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = '/my/crop-requests/%s' % rec.id

    def action_review(self):
        self.filtered(lambda r: r.state == 'new').write({'state': 'review', 'user_id': self.env.user.id})
        return True

    def action_approve(self):
        for rec in self:
            if rec.state not in ('new', 'review'):
                raise UserError(_('Only new or reviewed requests can be approved.'))
        self.write({'state': 'approved'})
        for rec in self:
            rec.message_post(body=_('Your crop request has been approved.'), message_type='comment',
                             subtype_xmlid='mail.mt_comment')
        return True

    def action_reject(self):
        for rec in self:
            if rec.state in ('converted',):
                raise UserError(_('A request in production cannot be rejected.'))
        self.write({'state': 'rejected'})
        for rec in self:
            rec.message_post(body=_('Your crop request was declined. %s', rec.reject_reason or ''),
                             message_type='comment', subtype_xmlid='mail.mt_comment')
        return True

    def action_cancel(self):
        self.filtered(lambda r: r.state not in ('converted',)).write({'state': 'cancelled'})
        return True

    def action_reset(self):
        self.filtered(lambda r: r.state in ('rejected', 'cancelled')).write({'state': 'new'})
        return True

    def action_convert_plan(self):
        self.ensure_one()
        if self.state not in ('review', 'approved'):
            raise UserError(_('Approve the request before planning it.'))
        return {'type': 'ir.actions.act_window', 'name': _('Plan Crop'), 'res_model': 'mdv.agri.request.plan.wizard',
                'view_mode': 'form', 'target': 'new', 'context': {'default_request_id': self.id}}

    def _create_plan(self, field, season, sowing_date):
        self.ensure_one()
        area = self.area_ha or (self.quantity / self.crop_id.expected_yield_per_ha
                                if self.crop_id.expected_yield_per_ha else field.area_ha)
        plan = self.env['mdv.agri.crop.plan'].create({
            'field_id': field.id, 'season_id': season.id, 'crop_id': self.crop_id.id,
            'variety_id': self.variety_id.id, 'sowing_date': sowing_date, 'request_id': self.id,
            'area_ha': min(area, field.area_ha) if field.area_ha else area, 'company_id': field.company_id.id,
        })
        self.write({'plan_id': plan.id, 'state': 'converted'})
        self.message_post(body=_('Your crop is planned on %(field)s, sowing %(date)s.', field=field.display_name,
                                 date=sowing_date), message_type='comment', subtype_xmlid='mail.mt_comment')
        return plan

    def _crop_product(self):
        self.ensure_one()
        product = self.crop_id.product_id
        if not product:
            raise UserError(_('Set the harvest product of crop %s first.', self.crop_id.name))
        return product

    def action_create_purchase(self):
        """Contract grower: buy the crop from the partner farmer."""
        self.ensure_one()
        if self.state not in ('review', 'approved'):
            raise UserError(_('Approve the request first.'))
        if self.purchase_order_id:
            raise UserError(_('A purchase order already exists.'))
        product = self._crop_product()
        order = self.env['purchase.order'].create({
            'partner_id': self.partner_id.id, 'company_id': self.company_id.id, 'origin': self.name,
            'mdv_crop_request_id': self.id, 'date_planned': self.desired_date or fields.Datetime.now(),
            'order_line': [(0, 0, {'product_id': product.id, 'product_qty': self.quantity or 1.0,
                                   'price_unit': self.price_unit or product.standard_price})],
        })
        self.write({'purchase_order_id': order.id, 'state': 'converted'})
        return {'type': 'ir.actions.act_window', 'res_model': 'purchase.order', 'res_id': order.id, 'view_mode': 'form'}

    def action_create_quotation(self):
        """Grow-and-supply: quote the crop to the customer."""
        self.ensure_one()
        if self.sale_order_id:
            raise UserError(_('A quotation already exists.'))
        product = self._crop_product()
        line_vals = {'product_id': product.id, 'product_uom_qty': self.quantity or 1.0,
                     'mdv_crop_plan_id': self.plan_id.id}
        if self.price_unit:
            line_vals['price_unit'] = self.price_unit
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id, 'company_id': self.company_id.id, 'origin': self.name,
            'mdv_crop_request_id': self.id, 'commitment_date': self.desired_date,
            'order_line': [(0, 0, line_vals)],
        })
        self.sale_order_id = order
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': order.id, 'view_mode': 'form'}

    def action_view_plan(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'mdv.agri.crop.plan', 'res_id': self.plan_id.id,
                'view_mode': 'form'}
