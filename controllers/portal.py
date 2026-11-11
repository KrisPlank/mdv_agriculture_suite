from odoo import _, fields, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

REQUEST_TYPES = ('supply', 'grower', 'service')


class AgriCropRequestPortal(CustomerPortal):

    def _crop_request_domain(self):
        partner = request.env.user.partner_id
        return [('partner_id', 'child_of', partner.commercial_partner_id.id)]

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'crop_request_count' in counters:
            Request = request.env['mdv.agri.crop.request']
            values['crop_request_count'] = Request.search_count(self._crop_request_domain()) \
                if Request.has_access('read') else 0
        return values

    def _crop_form_values(self, error=None, values=None):
        return {
            'page_name': 'crop_request_new',
            'crops': request.env['mdv.agri.crop'].sudo().search([('active', '=', True)]),
            'request_types': request.env['mdv.agri.crop.request']._fields['request_type'].selection,
            'error': error or {},
            'values': values or {},
        }

    @http.route(['/my/crop-requests', '/my/crop-requests/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_crop_requests(self, page=1, sortby=None, **kw):
        Request = request.env['mdv.agri.crop.request']
        domain = self._crop_request_domain()
        sortings = {'date': {'label': _('Newest'), 'order': 'create_date desc'},
                    'state': {'label': _('Status'), 'order': 'state, create_date desc'}}
        sortby = sortby if sortby in sortings else 'date'
        count = Request.search_count(domain)
        pager = portal_pager(url='/my/crop-requests', total=count, page=page, step=self._items_per_page,
                             url_args={'sortby': sortby})
        records = Request.search(domain, order=sortings[sortby]['order'], limit=self._items_per_page,
                                 offset=pager['offset'])
        return request.render('mdv_agriculture_suite.portal_my_crop_requests', {
            'crop_requests': records.sudo(), 'page_name': 'crop_request', 'pager': pager, 'sortby': sortby,
            'searchbar_sortings': sortings, 'default_url': '/my/crop-requests',
        })

    @http.route(['/my/crop-requests/<int:request_id>'], type='http', auth='public', website=True)
    def portal_crop_request_page(self, request_id, access_token=None, **kw):
        try:
            record = self._document_check_access('mdv.agri.crop.request', request_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        values = self._get_page_view_values(record, access_token, {
            'crop_request': record, 'page_name': 'crop_request', 'token': access_token,
        }, 'my_crop_requests_history', False)
        return request.render('mdv_agriculture_suite.portal_crop_request_page', values)

    @http.route(['/my/crop-requests/new'], type='http', auth='user', website=True, methods=['GET'])
    def portal_crop_request_new(self, **kw):
        return request.render('mdv_agriculture_suite.portal_crop_request_form', self._crop_form_values())

    @http.route(['/my/crop-requests/submit'], type='http', auth='user', website=True, methods=['POST'])
    def portal_crop_request_submit(self, **post):
        vals, error = self._parse_request_form(post)
        if error:
            values = self._crop_form_values(error, post)
            return request.render('mdv_agriculture_suite.portal_crop_request_form', values)
        vals.update(partner_id=request.env.user.partner_id.id, source='portal')
        record = request.env['mdv.agri.crop.request'].sudo().create(vals)
        return request.redirect('/my/crop-requests/%s?submitted=1' % record.id)

    @http.route(['/crop-request'], type='http', auth='public', website=True, methods=['GET'], sitemap=True)
    def website_crop_request(self, **kw):
        values = self._crop_form_values()
        values['page_name'] = 'crop_request_public'
        return request.render('mdv_agriculture_suite.website_crop_request', values)

    @http.route(['/crop-request/submit'], type='http', auth='public', website=True, methods=['POST'])
    def website_crop_request_submit(self, **post):
        vals, error = self._parse_request_form(post)
        if request.env.user._is_public():
            for key in ('contact_name', 'email'):
                if not (post.get(key) or '').strip():
                    error[key] = True
            if post.get('email') and '@' not in post['email']:
                error['email'] = True
        if error:
            values = self._crop_form_values(error, post)
            values['page_name'] = 'crop_request_public'
            return request.render('mdv_agriculture_suite.website_crop_request', values)
        if request.env.user._is_public():
            partner = request.env['res.partner'].sudo().create({
                'name': post['contact_name'].strip(), 'email': post['email'].strip(),
                'phone': (post.get('phone') or '').strip() or False,
                'company_name': (post.get('company') or '').strip() or False,
            })
        else:
            partner = request.env.user.partner_id
        vals.update(partner_id=partner.id, source='website')
        record = request.env['mdv.agri.crop.request'].sudo().create(vals)
        return request.render('mdv_agriculture_suite.website_crop_request_thanks', {'crop_request': record})

    def _parse_request_form(self, post):
        error = {}
        crop = request.env['mdv.agri.crop'].sudo().browse(int(post.get('crop_id') or 0)).exists()
        if not crop:
            error['crop_id'] = True
        request_type = post.get('request_type')
        if request_type not in REQUEST_TYPES:
            error['request_type'] = True

        def _float(key):
            try:
                value = float(post.get(key) or 0.0)
            except ValueError:
                error[key] = True
                return 0.0
            if value < 0:
                error[key] = True
            return value

        quantity = _float('quantity')
        area = _float('area_ha')
        if not quantity and not area:
            error['quantity'] = True
        desired = False
        if post.get('desired_date'):
            try:
                desired = fields.Date.to_date(post['desired_date'])
            except ValueError:
                error['desired_date'] = True
        vals = {
            'crop_id': crop.id, 'request_type': request_type, 'quantity': quantity, 'area_ha': area,
            'desired_date': desired, 'land_location': (post.get('land_location') or '').strip()[:200] or False,
            'description': (post.get('description') or '').strip()[:4000] or False,
            'company_id': request.env.company.id,
        }
        return vals, error
