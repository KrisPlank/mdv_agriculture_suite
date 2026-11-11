import math
from datetime import timedelta

from odoo import api, fields, models


class AgriFarmDemo(models.Model):
    _inherit = 'mdv.agri.farm'

    @api.model
    def _mdv_agri_demo_flow(self):
        """Run the real workflows on the demo records so every screen has consistent data."""
        ref = lambda xid: self.env.ref('mdv_agriculture_suite.' + xid)  # noqa: E731
        today = fields.Date.context_today(self)
        farm = ref('farm_northwind')
        company = farm.company_id
        location = farm._get_consumption_location()
        company.write({'mdv_agri_milk_product_id': ref('prod_milk').id, 'mdv_agri_egg_product_id': ref('prod_eggs').id})

        Quant = self.env['stock.quant']
        for xid, qty in [('prod_wheat_seed', 20000), ('prod_corn_seed', 3000), ('prod_tomato_seedling', 200000),
                         ('prod_urea', 60000), ('prod_npk', 40000), ('prod_herbicide', 600), ('prod_fungicide', 600),
                         ('prod_insecticide', 200), ('prod_dairy_feed', 9000), ('prod_hay', 12000),
                         ('prod_layer_mash', 6000), ('prod_goat_feed', 600), ('prod_vaccine_clostridial', 40),
                         ('prod_vaccine_nd', 5000), ('prod_antibiotic', 30), ('prod_semen', 10)]:
            Quant._update_available_quantity(ref(xid), location, qty)

        crew = {'machine': ref('emp_jordan'), 'manual': ref('emp_sam')}
        machines = {'spraying': ref('eq_sprayer'), 'harvest': ref('eq_combine')}

        def run_activities(plan, until):
            for act in plan.field_activity_ids.sorted('date_planned'):
                if act.date_planned > until or act.activity_type == 'harvest':
                    continue
                labour = act.planned_labour_hours or 1.0
                vals = {'date_done': act.date_planned,
                        'labour_line_ids': [(0, 0, {'employee_id': (crew['machine'] if act.planned_machine_hours
                                                                    else crew['manual']).id,
                                                    'hours': round(labour * 1.05, 1)})]}
                if act.planned_machine_hours:
                    vals['machine_line_ids'] = [(0, 0, {
                        'equipment_id': machines.get(act.activity_type, ref('eq_tractor')).id,
                        'operator_id': crew['machine'].id, 'hours': round(act.planned_machine_hours, 1)})]
                if act.activity_type == 'irrigation':
                    vals['water_m3'] = round(plan.area_ha * 250, 0)
                act.write(vals)
                act.action_done()

        def harvest(plan, qty, grade, moisture, date):
            rec = self.env['mdv.agri.harvest'].create({
                'plan_id': plan.id, 'quantity': qty, 'grade_id': ref(grade).id, 'moisture_pct': moisture, 'date': date,
            })
            rec.action_validate()
            act = plan.field_activity_ids.filtered(lambda a: a.activity_type == 'harvest' and a.state == 'planned')[:1]
            if act:
                act.write({'date_done': date, 'machine_line_ids': [(0, 0, {
                    'equipment_id': ref('eq_combine').id, 'operator_id': crew['machine'].id,
                    'hours': round(act.planned_machine_hours, 1)})] if act.planned_machine_hours else [],
                    'labour_line_ids': [(0, 0, {'employee_id': crew['manual'].id,
                                                'hours': round(act.planned_labour_hours or 4, 1)})]})
                act.action_done()
            return rec

        Plan = self.env['mdv.agri.crop.plan']
        prev = ref('season_prev')
        year = prev.date_start.year
        # previous season, run to the end
        wheat_prev = Plan.create({'season_id': prev.id, 'field_id': ref('field_north').id, 'crop_id': ref('crop_wheat').id,
                                  'variety_id': ref('variety_wheat_1').id, 'sowing_date': fields.Date.to_date('%s-03-20' % year)})
        corn_prev = Plan.create({'season_id': prev.id, 'field_id': ref('field_south').id, 'crop_id': ref('crop_corn').id,
                                 'variety_id': ref('variety_corn_1').id, 'sowing_date': fields.Date.to_date('%s-04-25' % year)})
        for plan, qty, grade, moist in [(wheat_prev, 0, 'grade_a', 13.5), (corn_prev, 0, 'grade_b', 15.0)]:
            plan.action_confirm()
            run_activities(plan, plan.expected_harvest_date)
            factor = 1.04 if plan == wheat_prev else 0.93
            hv = harvest(plan, round(plan.expected_yield * factor, -1), grade, moist, plan.expected_harvest_date)
            plan.action_mark_harvested()
            plan.action_close()
            wiz = self.env['mdv.agri.harvest.sell.wizard'].create({'partner_id': ref('partner_riverside').id,
                                                                    'harvest_ids': [(6, 0, hv.ids)]})
            for line in wiz.line_ids:
                line.quantity = round(line.quantity * 0.8, 0)
            order = self.env['sale.order'].browse(wiz.action_create()['res_id'])
            order.action_confirm()

        # current season
        cur = ref('season_current')
        wheat = Plan.create({'season_id': cur.id, 'field_id': ref('field_north').id, 'crop_id': ref('crop_wheat').id,
                             'variety_id': ref('variety_wheat_1').id, 'sowing_date': today - timedelta(days=120),
                             'responsible_id': self.env.ref('base.user_admin').id})
        corn = Plan.create({'season_id': cur.id, 'field_id': ref('field_south').id, 'crop_id': ref('crop_corn').id,
                            'variety_id': ref('variety_corn_1').id, 'sowing_date': today - timedelta(days=70)})
        tomato = Plan.create({'season_id': cur.id, 'field_id': ref('field_river').id, 'crop_id': ref('crop_tomato').id,
                              'variety_id': ref('variety_tomato_1').id, 'sowing_date': today - timedelta(days=100)})
        Plan.create({'season_id': cur.id, 'field_id': ref('field_east').id, 'crop_id': ref('crop_corn').id,
                     'sowing_date': today + timedelta(days=20), 'area_ha': 10.0,
                     'notes': '<p>Scenario: convert part of East Pasture to corn next spring.</p>'})
        for plan in (wheat, corn, tomato):
            plan.action_confirm()
            run_activities(plan, today - timedelta(days=1))
        tomato.action_add_lease_cost()
        harvest(tomato, 18500, 'grade_a', 0.0, today - timedelta(days=4))
        harvest(tomato, 6200, 'grade_b', 0.0, today - timedelta(days=1))

        Scout = self.env['mdv.agri.scouting']
        Scout.create({'plan_id': wheat.id, 'pest_id': ref('pest_aphid').id, 'severity': 'medium', 'incidence_pct': 18,
                      'affected_area_ha': 6.0, 'growth_stage': 'flowering', 'date': today - timedelta(days=2),
                      'observation': 'Colonies on the north headland, 15-20 aphids per tiller on 1 in 5 plants.'})
        blight = Scout.create({'plan_id': corn.id, 'pest_id': ref('pest_nclb').id, 'severity': 'high', 'incidence_pct': 35,
                               'affected_area_ha': 12.0, 'growth_stage': 'vegetative', 'date': today - timedelta(days=1),
                               'observation': 'Cigar-shaped grey lesions on the lower leaves in the wetter south-west corner.'})
        blight.action_create_spray()
        Scout.create({'plan_id': tomato.id, 'pest_id': ref('pest_blight').id, 'severity': 'low', 'incidence_pct': 2,
                      'affected_area_ha': 0.5, 'growth_stage': 'fruiting', 'date': today - timedelta(days=12),
                      'state': 'closed', 'observation': 'Two plants with lesions near the river, removed.'})

        # weather: 60 observed days and a 3-day forecast (sample values, replaced by Open-Meteo once fetched)
        Weather = self.env['mdv.agri.weather.log']
        vals_list = []
        for offset in range(-60, 4):
            day = today + timedelta(days=offset)
            t_mean = 14 + 9 * math.sin((day.timetuple().tm_yday - 105) / 365.0 * 2 * math.pi) + 3 * math.sin(offset / 3.0)
            rain = max(0.0, round(12 * math.sin(offset * 1.7) - 6, 1))
            vals_list.append({
                'farm_id': farm.id, 'date': day, 'source': 'manual', 'is_forecast': offset > 0,
                'temp_min_c': round(t_mean - 6 if offset != 2 else -1.5, 1), 'temp_max_c': round(t_mean + 6, 1),
                'temp_mean_c': round(t_mean, 1), 'precipitation_mm': rain if offset != 1 else 31.0,
                'rain_mm': rain, 'humidity_pct': 60 + (offset % 5) * 4, 'wind_max_kmh': 14 + (offset % 7) * 3,
                'wind_gust_kmh': 28 + (offset % 7) * 4, 'et0_mm': round(2.5 + math.sin(offset / 4.0), 2),
            })
        Weather.create(vals_list)._notify_alerts()

        # livestock
        cows = [ref(x) for x in ('cow_daisy', 'cow_bella', 'cow_rosie', 'cow_clover', 'cow_maple', 'cow_hazel')]
        clover = ref('cow_clover')
        treat = self.env['mdv.agri.vet.treatment'].create({
            'animal_id': clover.id, 'treatment_type': 'treatment', 'date': today - timedelta(days=2),
            'diagnosis': 'Clinical mastitis, rear left quarter', 'vet_partner_id': ref('partner_vet').id, 'vet_fee': 85.0,
            'withdrawal_days': 4, 'medicine_line_ids': [(0, 0, {'product_id': ref('prod_antibiotic').id, 'quantity': 3,
                                                                 'dosage': '1 tube per milking'})],
        })
        treat.action_done()
        MilkLog = self.env['mdv.agri.milk.log']
        milk_vals = []
        for offset in range(13, -1, -1):
            day = today - timedelta(days=offset)
            for idx, cow in enumerate(cows):
                base = 14.5 + idx * 0.9 - (cow.last_birth_date and (today - cow.last_birth_date).days / 60.0 or 0)
                for session, factor in (('am', 1.0), ('pm', 0.86)):
                    milk_vals.append({'animal_id': cow.id, 'date': day, 'session': session,
                                      'quantity_l': round(max(6.0, base * factor + math.sin(offset + idx) * 0.8), 1),
                                      'fat_pct': round(3.7 + (idx % 3) * 0.15, 2), 'protein_pct': round(3.2 + (idx % 2) * 0.1, 2),
                                      'scc': 140 + idx * 25 + (400 if cow == clover and offset <= 3 else 0)})
        logs = MilkLog.create(milk_vals)
        logs.filtered(lambda m: m.date < today - timedelta(days=1)).action_post_to_stock()

        Breeding = self.env['mdv.agri.breeding']
        bella = Breeding.create({'animal_id': ref('cow_bella').id, 'date': today - timedelta(days=45), 'method': 'ai',
                                 'sire_id': ref('animal_duke').id, 'technician_id': ref('partner_vet').id})
        bella.action_confirm_pregnant()
        Breeding.create({'animal_id': ref('cow_rosie').id, 'date': today - timedelta(days=12), 'method': 'ai',
                         'semen_ref': 'HO-2291 sexed', 'semen_product_id': ref('prod_semen').id,
                         'technician_id': ref('partner_vet').id})
        hazel = Breeding.create({'animal_id': ref('cow_hazel').id, 'date': today - timedelta(days=300), 'method': 'natural',
                                 'sire_id': ref('animal_duke').id})
        hazel._register_birth(today - timedelta(days=20), [{'tag': 'NW-301', 'name': 'Hazel 23', 'sex': 'female',
                                                            'weight_kg': 41.0}])

        flock = ref('herd_layers')
        self.env['mdv.agri.mortality'].create([
            {'herd_id': flock.id, 'date': today - timedelta(days=9), 'count': 3, 'cause': 'disease'},
            {'herd_id': flock.id, 'date': today - timedelta(days=4), 'count': 1, 'cause': 'predator'},
        ])
        EggLog = self.env['mdv.agri.egg.log']
        eggs = EggLog.create([{
            'herd_id': flock.id, 'date': today - timedelta(days=offset),
            'eggs_collected': int(flock.current_count * (0.89 + math.sin(offset) * 0.025)),
            'eggs_broken': 6 + offset % 4, 'avg_egg_weight_g': round(61 + math.sin(offset / 2.0), 1),
        } for offset in range(13, -1, -1)])
        eggs.filtered(lambda e: e.date < today).action_post_to_stock()
        for offset in range(6, -1, -1):
            for herd in (ref('herd_dairy'), flock, ref('herd_goats')):
                herd.action_record_daily_feed(today - timedelta(days=offset))
        self.env['mdv.agri.vaccination.schedule'].search([])._generate_due(today)

        Request = self.env['mdv.agri.crop.request']
        Request.create({'partner_id': ref('partner_riverside').id, 'request_type': 'supply', 'crop_id': ref('crop_wheat').id,
                        'quantity': 50000, 'desired_date': today + timedelta(days=200), 'price_unit': 0.23,
                        'source': 'website', 'description': 'Milling wheat, protein 12.5% or more, delivered in two loads.'})
        req = Request.create({'partner_id': ref('partner_morgan_farm').id, 'request_type': 'grower',
                              'crop_id': ref('crop_corn').id, 'quantity': 80000, 'area_ha': 8.0, 'price_unit': 0.18,
                              'source': 'portal', 'desired_date': today + timedelta(days=150),
                              'description': 'We can grow 8 ha of corn for you on our land next to the river.'})
        req.action_review()
        req2 = Request.create({'partner_id': ref('partner_pinecrest').id, 'request_type': 'service',
                               'crop_id': ref('crop_tomato').id, 'area_ha': 5.0, 'land_location': 'Pinecrest plot, County Road 12',
                               'desired_date': today + timedelta(days=120)})
        req2.action_approve()

        # the demo runs as the superuser: hand the records to the demo administrator
        admin = self.env.ref('base.user_admin')
        Plan.search([]).write({'responsible_id': admin.id})
        self.env['mdv.agri.activity'].search([]).write({'user_id': admin.id})
        self.env['mdv.agri.scouting'].search([]).write({'scout_id': admin.id})
        self.env['mdv.agri.harvest'].search([]).write({'user_id': admin.id})
        self.env['mdv.agri.crop.request'].search([('state', '!=', 'new')]).write({'user_id': admin.id})
        return True
