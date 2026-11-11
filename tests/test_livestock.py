from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import AgriCommon


@tagged('post_install', '-at_install')
class TestLivestock(AgriCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.herd = cls.env['mdv.agri.herd'].create({
            'name': 'Test Dairy', 'farm_id': cls.farm.id, 'species_id': cls.cattle.id, 'herd_type': 'dairy',
            'ration_line_ids': [Command.create({'product_id': cls.feed.id, 'qty_per_head': 8.0})]})
        Animal = cls.env['mdv.agri.animal']
        cls.bull = Animal.create({'tag': 'T-900', 'name': 'Bull', 'species_id': cls.cattle.id, 'sex': 'male',
                                  'farm_id': cls.farm.id})
        cls.cow = Animal.create({'tag': 'T-101', 'name': 'Daisy', 'species_id': cls.cattle.id, 'sex': 'female',
                                 'herd_id': cls.herd.id, 'lactation_status': 'lactating',
                                 'birth_date': cls.today - timedelta(days=1500)})
        cls.cow2 = Animal.create({'tag': 'T-102', 'name': 'Bella', 'species_id': cls.cattle.id, 'sex': 'female',
                                  'herd_id': cls.herd.id, 'birth_date': cls.today - timedelta(days=1200)})
        cls.flock = cls.env['mdv.agri.herd'].create({
            'name': 'Test Layers', 'farm_id': cls.farm.id, 'species_id': cls.poultry.id, 'herd_type': 'layers',
            'is_flock': True, 'initial_count': 1000, 'placement_date': cls.today - timedelta(days=150)})

    def test_herd_counts(self):
        self.assertEqual(self.herd.current_count, 2)
        self.assertEqual(self.cow.farm_id, self.farm, 'farm follows the herd')
        self.assertEqual(self.flock.current_count, 1000)
        self.assertEqual(self.flock.age_weeks, 21)

    def test_flock_mortality(self):
        self.env['mdv.agri.mortality'].create({'herd_id': self.flock.id, 'count': 12, 'cause': 'disease'})
        self.assertEqual(self.flock.current_count, 988)
        self.assertAlmostEqual(self.flock.mortality_pct, 1.2)
        with self.assertRaises(ValidationError):
            self.env['mdv.agri.mortality'].create({'herd_id': self.flock.id, 'count': 2000})

    def test_animal_mortality_marks_dead(self):
        self.env['mdv.agri.mortality'].create({'herd_id': self.herd.id, 'animal_id': self.cow2.id, 'cause': 'injury'})
        self.assertEqual(self.cow2.status, 'dead')
        self.assertEqual(self.herd.current_count, 1)

    def test_parent_constraints(self):
        with self.assertRaises(ValidationError):
            self.cow2.dam_id = self.bull
        with self.assertRaises(ValidationError):
            self.cow2.sire_id = self.cow
        goat = self.env['mdv.agri.animal'].create({'tag': 'G-1', 'species_id': self.env.ref(
            'mdv_agriculture_suite.species_goat').id, 'sex': 'female'})
        with self.assertRaises(ValidationError):
            goat.dam_id = self.cow

    @mute_logger('odoo.sql_db')
    def test_ear_tag_unique(self):
        with self.assertRaises(IntegrityError):
            self.env['mdv.agri.animal'].create({'tag': 'T-101', 'species_id': self.cattle.id})
            self.env.flush_all()

    def test_breeding_dates_and_pregnancy(self):
        service = self.today - timedelta(days=40)
        breeding = self.env['mdv.agri.breeding'].create({'animal_id': self.cow2.id, 'date': service,
                                                         'sire_id': self.bull.id})
        self.assertTrue(breeding.name.startswith('BR/'))
        self.assertEqual(breeding.expected_birth_date, service + timedelta(days=283))
        self.assertEqual(breeding.pregnancy_check_date, service + timedelta(days=35))
        self.assertEqual(self.cow2.reproductive_status, 'inseminated')
        breeding.action_confirm_pregnant()
        self.assertEqual(self.cow2.reproductive_status, 'pregnant')
        self.assertEqual(self.cow2.expected_birth_date, breeding.expected_birth_date)

    def test_breeding_on_male_refused(self):
        with self.assertRaises(ValidationError):
            self.env['mdv.agri.breeding'].create({'animal_id': self.bull.id})

    def test_register_birth(self):
        breeding = self.env['mdv.agri.breeding'].create({'animal_id': self.cow2.id, 'sire_id': self.bull.id,
                                                         'date': self.today - timedelta(days=280)})
        breeding.action_confirm_pregnant()
        action = breeding.action_register_birth()
        wizard = self.env['mdv.agri.birth.wizard'].with_context(action['context']).create({
            'line_ids': [Command.create({'tag': 'T-301', 'sex': 'female', 'weight_kg': 40})]})
        wizard.action_register()
        calf = self.env['mdv.agri.animal'].search([('tag', '=', 'T-301')])
        self.assertEqual(calf.dam_id, self.cow2)
        self.assertEqual(calf.sire_id, self.bull)
        self.assertEqual(calf.herd_id, self.herd)
        self.assertEqual(calf.weight_kg, 40)
        self.assertEqual(breeding.state, 'delivered')
        self.assertEqual(self.cow2.lactation_status, 'lactating')
        self.assertEqual(self.cow2.reproductive_status, 'open')
        self.assertIn(calf, self.cow2.offspring_ids)

    def test_semen_straw_is_consumed(self):
        straw = self.env['product.product'].create({'name': 'Straw', 'type': 'consu', 'is_storable': True})
        self.env['stock.quant']._update_available_quantity(straw, self.stock_loc, 3)
        breeding = self.env['mdv.agri.breeding'].create({'animal_id': self.cow.id, 'semen_product_id': straw.id})
        self.assertEqual(breeding.move_id.state, 'done')
        self.assertAlmostEqual(self._qty(straw), 2)

    def test_vet_treatment_consumes_medicine_and_costs(self):
        treat = self.env['mdv.agri.vet.treatment'].create({
            'animal_id': self.cow.id, 'diagnosis': 'Mastitis', 'vet_fee': 60.0, 'withdrawal_days': 4,
            'medicine_line_ids': [Command.create({'product_id': self.drug.id, 'quantity': 3})]})
        self.assertEqual(treat.herd_id, self.herd)
        treat.action_done()
        self.assertAlmostEqual(self._qty(self.drug), 17)
        self.assertAlmostEqual(treat.total_cost, 75.0)
        self.assertAlmostEqual(self.herd.vet_cost, 75.0)
        self.assertEqual(treat.withdrawal_until, self.today + timedelta(days=4))
        self.assertEqual(self.cow.withdrawal_until, self.today + timedelta(days=4))

    def test_vet_bill(self):
        self.herd.action_create_analytic_account()
        vet = self.env['res.partner'].create({'name': 'Vet'})
        treat = self.env['mdv.agri.vet.treatment'].create({'herd_id': self.herd.id, 'vet_partner_id': vet.id,
                                                           'vet_fee': 120.0})
        treat.action_done()
        treat.action_create_bill()
        bill = treat.bill_id
        self.assertEqual(bill.move_type, 'in_invoice')
        self.assertAlmostEqual(bill.amount_untaxed, 120.0)
        self.assertEqual(bill.invoice_line_ids.analytic_distribution,
                         {str(self.herd.analytic_account_id.id): 100})

    def test_milk_in_withdrawal_is_discarded(self):
        treat = self.env['mdv.agri.vet.treatment'].create({'animal_id': self.cow.id, 'withdrawal_days': 3})
        treat.action_done()
        MilkLog = self.env['mdv.agri.milk.log']
        bad = MilkLog.create({'animal_id': self.cow.id, 'quantity_l': 12, 'session': 'am'})
        good = MilkLog.create({'animal_id': self.cow.id, 'quantity_l': 11, 'session': 'am',
                               'date': self.today + timedelta(days=5)})
        before = MilkLog.create({'animal_id': self.cow.id, 'quantity_l': 13, 'session': 'pm',
                                 'date': self.today - timedelta(days=2)})
        self.assertFalse(before.discarded, 'milk from before the treatment stays in the tank')
        self.assertTrue(bad.in_withdrawal and bad.discarded)
        self.assertFalse(good.discarded)
        self.assertEqual(bad.herd_id, self.herd)

    def test_milk_post_to_stock(self):
        MilkLog = self.env['mdv.agri.milk.log']
        logs = MilkLog.create([
            {'animal_id': self.cow.id, 'quantity_l': 14, 'session': 'am'},
            {'animal_id': self.cow.id, 'quantity_l': 12, 'session': 'pm'},
            {'animal_id': self.cow2.id, 'quantity_l': 9, 'session': 'am', 'discarded': True},
        ])
        logs.action_post_to_stock()
        self.assertAlmostEqual(self._qty(self.milk), 26)
        self.assertEqual(logs.filtered('posted').mapped('quantity_l'), [14, 12])
        with self.assertRaises(UserError):
            logs.action_post_to_stock()
        self.assertAlmostEqual(self.herd.milk_7d, 26)
        self.assertAlmostEqual(self.cow.milk_7d, 26)

    def test_milk_session_unique_per_animal(self):
        MilkLog = self.env['mdv.agri.milk.log']
        MilkLog.create({'animal_id': self.cow.id, 'quantity_l': 14, 'session': 'am'})
        with self.assertRaises(ValidationError):
            MilkLog.create({'animal_id': self.cow.id, 'quantity_l': 10, 'session': 'am'})

    def test_egg_production_and_stock(self):
        log = self.env['mdv.agri.egg.log'].create({'herd_id': self.flock.id, 'eggs_collected': 900,
                                                   'eggs_broken': 15})
        self.assertEqual(log.birds_count, 1000)
        self.assertEqual(log.eggs_saleable, 885)
        self.assertAlmostEqual(log.lay_rate_pct, 90.0)
        log.action_post_to_stock()
        self.assertAlmostEqual(self._qty(self.eggs), 885)
        self.assertAlmostEqual(self.flock.lay_rate_7d, 90.0)
        with self.assertRaises(ValidationError):
            self.env['mdv.agri.egg.log'].create({'herd_id': self.flock.id, 'eggs_collected': 10, 'eggs_broken': 20,
                                                 'date': self.today - timedelta(days=1)})

    def test_daily_ration_feed(self):
        before = self._qty(self.feed)
        logs = self.herd.action_record_daily_feed()
        self.assertEqual(len(logs), 1)
        self.assertAlmostEqual(logs.quantity, 16.0)
        self.assertEqual(logs.state, 'done')
        self.assertAlmostEqual(self._qty(self.feed), before - 16)
        self.assertAlmostEqual(self.herd.feed_cost, 16 * 0.4)
        with self.assertRaises(UserError):
            self.herd.action_record_daily_feed()

    def test_feed_per_litre(self):
        self.herd.action_record_daily_feed()
        self.env['mdv.agri.milk.log'].create({'animal_id': self.cow.id, 'quantity_l': 32, 'session': 'day'})
        self.assertAlmostEqual(self.herd.feed_per_litre, 0.5)

    def test_vaccination_schedule_plans_due_doses(self):
        sched = self.env['mdv.agri.vaccination.schedule'].create({
            'name': 'ND booster', 'species_id': self.poultry.id, 'herd_type': 'layers', 'product_id': self.vaccine.id,
            'first_age_days': 7, 'repeat_days': 60, 'lead_days': 14})
        created = sched._generate_due(self.today).filtered(lambda t: t.herd_id == self.flock)
        self.assertEqual(len(created), 1)
        self.assertEqual(created.herd_id, self.flock)
        self.assertEqual(created.date, self.today, 'an overdue first dose is planned for today')
        self.assertEqual(created.medicine_line_ids.quantity, 1000)
        mine = lambda recs: recs.filtered(lambda t: t.herd_id == self.flock)  # noqa: E731
        self.assertFalse(mine(sched._generate_due(self.today)), 'no duplicate while one is planned')
        created.action_done()
        self.assertFalse(mine(sched._generate_due(self.today)), 'next dose is 60 days away')
        nxt = mine(sched._generate_due(self.today + timedelta(days=50)))
        self.assertEqual(nxt.date, self.today + timedelta(days=60))

    def test_vaccination_for_individual_animals(self):
        sched = self.env['mdv.agri.vaccination.schedule'].create({
            'name': 'Clostridial', 'species_id': self.cattle.id, 'first_age_days': 90, 'repeat_days': 365})
        created = sched._generate_due(self.today).filtered(lambda t: t.animal_id in (self.cow | self.cow2 | self.bull))
        self.assertEqual(set(created.mapped('animal_id').ids), {self.cow.id, self.cow2.id}, 'the bull has no birth date')
        self.assertTrue(all(t.treatment_type == 'vaccination' for t in created))

    def test_weight_gain(self):
        self.cow.weight_log_ids = [Command.create({'date': self.today - timedelta(days=10), 'weight_kg': 600}),
                                   Command.create({'date': self.today, 'weight_kg': 610})]
        self.assertEqual(self.cow.weight_kg, 610)
        latest = self.cow.weight_log_ids.filtered(lambda w: w.date == self.today)
        self.assertAlmostEqual(latest.daily_gain_kg, 1.0)
