from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

COST_TYPES = [
    ('material', 'Materials'),
    ('labour', 'Labour'),
    ('machine', 'Machinery'),
    ('overhead', 'Overhead'),
    ('feed', 'Feed'),
    ('vet', 'Veterinary'),
]


class AgriStockMixin(models.AbstractModel):
    _name = 'mdv.agri.stock.mixin'
    _description = 'Farm stock helpers'

    def _agri_production_location(self, product, company):
        location = product.with_company(company).property_stock_production
        if not location:
            location = self.env['stock.location'].search(
                [('usage', '=', 'production'), ('company_id', 'in', (company.id, False))], limit=1)
        if not location:
            raise UserError(_('No production (virtual) location found for %s.', company.name))
        return location

    def _agri_check_availability(self, lines, location, company):
        """lines: list of (product, qty). Raise if storable products are short and negative stock is off."""
        if company.mdv_agri_allow_negative:
            return
        missing = []
        Quant = self.env['stock.quant'].sudo()
        needed = {}
        for product, qty in lines:
            if product.is_storable:
                needed[product] = needed.get(product, 0.0) + qty
        for product, qty in needed.items():
            available = Quant._get_available_quantity(product, location)
            if float_compare(available, qty, precision_rounding=product.uom_id.rounding) < 0:
                missing.append(_('%(product)s: need %(need)s, available %(available)s in %(location)s',
                                 product=product.display_name, need=qty, available=available,
                                 location=location.display_name))
        if missing:
            raise UserError(_('Not enough stock to consume:\n%s\n\nReceive the stock first or allow '
                              'consumption without stock in the agriculture settings.', '\n'.join(missing)))

    def _agri_consume(self, lines, location, company, origin):
        """Consume (product, qty, uom) from an internal location into the production location.

        Returns the done stock moves.
        """
        Move = self.env['stock.move'].sudo()
        moves = Move
        lines = [(p, q, u) for p, q, u in lines if p and not float_is_zero(q, precision_digits=6)]
        self._agri_check_availability([(p, u._compute_quantity(q, p.uom_id)) for p, q, u in lines], location, company)
        for product, qty, uom in lines:
            move = Move.create({
                'product_id': product.id,
                'product_uom': (uom or product.uom_id).id,
                'product_uom_qty': qty,
                'location_id': location.id,
                'location_dest_id': self._agri_production_location(product, company).id,
                'company_id': company.id,
                'origin': origin,
            })
            moves |= move
        if moves:
            moves._action_confirm()
            moves._action_assign()
            for move in moves:
                if float_compare(move.quantity, move.product_uom_qty, precision_rounding=move.product_uom.rounding):
                    move.quantity = move.product_uom_qty
            moves.picked = True
            moves._action_done()
        return moves

    def _agri_receive(self, product, qty, uom, location, company, origin, lot=False):
        """Receive produce (harvest, milk, eggs) from the production location into the farm location."""
        if float_is_zero(qty, precision_digits=6):
            return self.env['stock.move']
        move = self.env['stock.move'].sudo().create({
            'product_id': product.id,
            'product_uom': (uom or product.uom_id).id,
            'product_uom_qty': qty,
            'location_id': self._agri_production_location(product, company).id,
            'location_dest_id': location.id,
            'company_id': company.id,
            'origin': origin,
        })
        move._action_confirm()
        move._action_assign()
        if float_compare(move.quantity, move.product_uom_qty, precision_rounding=move.product_uom.rounding):
            move.quantity = move.product_uom_qty
        if lot:
            move.move_line_ids.write({'lot_id': lot.id})
        move.picked = True
        move._action_done()
        return move

    def _agri_reverse(self, moves, origin):
        """Return done moves to where they came from (used when a done record is reset)."""
        Move = self.env['stock.move'].sudo()
        returns = Move
        for move in moves.filtered(lambda m: m.state == 'done'):
            ret = Move.create({
                'product_id': move.product_id.id,
                'product_uom': move.product_uom.id,
                'product_uom_qty': move.quantity,
                'location_id': move.location_dest_id.id,
                'location_dest_id': move.location_id.id,
                'company_id': move.company_id.id,
                'origin': origin,
            })
            ret._action_confirm()
            ret._action_assign()
            if float_compare(ret.quantity, ret.product_uom_qty, precision_rounding=ret.product_uom.rounding):
                ret.quantity = ret.product_uom_qty
            lots = move.move_line_ids.lot_id
            if lots:
                ret.move_line_ids.write({'lot_id': lots[:1].id})
            ret.picked = True
            ret._action_done()
            returns |= ret
        return returns


class AgriCostLine(models.Model):
    _name = 'mdv.agri.cost.line'
    _description = 'Farm Cost Entry'
    _order = 'date desc, id desc'

    name = fields.Char(required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    cost_type = fields.Selection(COST_TYPES, required=True)
    plan_id = fields.Many2one('mdv.agri.crop.plan', ondelete='cascade', index=True)
    activity_id = fields.Many2one('mdv.agri.activity', ondelete='cascade', index=True)
    herd_id = fields.Many2one('mdv.agri.herd', ondelete='cascade', index=True)
    animal_id = fields.Many2one('mdv.agri.animal', ondelete='set null')
    farm_id = fields.Many2one('mdv.agri.farm', index=True)
    field_id = fields.Many2one('mdv.agri.field')
    season_id = fields.Many2one('mdv.agri.season', related='plan_id.season_id', store=True)
    crop_id = fields.Many2one('mdv.agri.crop', related='plan_id.crop_id', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    product_id = fields.Many2one('product.product')
    employee_id = fields.Many2one('hr.employee')
    equipment_id = fields.Many2one('maintenance.equipment')
    quantity = fields.Float(digits='Product Unit')
    unit_label = fields.Char('Unit')
    unit_cost = fields.Float(digits='Product Price')
    amount = fields.Monetary(currency_field='currency_id')
    analytic_line_id = fields.Many2one('account.analytic.line', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._create_analytic_lines()
        return lines

    def unlink(self):
        analytic = self.mapped('analytic_line_id')
        res = super().unlink()
        analytic.sudo().unlink()
        return res

    def _create_analytic_lines(self):
        AnalyticLine = self.env['account.analytic.line'].sudo()
        for line in self:
            account = line.plan_id.analytic_account_id or line.herd_id.analytic_account_id
            if not account or float_is_zero(line.amount, precision_rounding=line.currency_id.rounding):
                continue
            line.analytic_line_id = AnalyticLine.create({
                'name': line.name,
                'date': line.date,
                'account_id': account.id,
                'amount': -line.amount,
                'unit_amount': line.quantity,
                'product_id': line.product_id.id,
                'company_id': line.company_id.id,
                'mdv_agri_cost_line_id': line.id,
            })


class AgriBudgetLine(models.Model):
    _name = 'mdv.agri.budget.line'
    _description = 'Crop Plan Budget Line'
    _order = 'plan_id, cost_type, id'

    plan_id = fields.Many2one('mdv.agri.crop.plan', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    currency_id = fields.Many2one(related='plan_id.currency_id')
    cost_type = fields.Selection(COST_TYPES, required=True, default='material')
    name = fields.Char(required=True)
    product_id = fields.Many2one('product.product')
    quantity = fields.Float(default=1.0, digits='Product Unit')
    unit_cost = fields.Float(digits='Product Price')
    amount = fields.Monetary(compute='_compute_amount', store=True, currency_field='currency_id')

    @api.depends('quantity', 'unit_cost')
    def _compute_amount(self):
        for line in self:
            line.amount = line.quantity * line.unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.unit_cost = self.product_id.standard_price


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    mdv_agri_cost_line_id = fields.Many2one('mdv.agri.cost.line', 'Farm Cost Entry', index='btree_not_null',
                                            ondelete='set null')
