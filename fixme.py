from time import sleep
import random
from decimal import Decimal
import pytz
import datetime

from django.utils import timezone

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.common.action_chains import ActionChains

from greenphire.testing.cc_mock import (
    cc_mock_init,
    get_address,
    get_site_study,
    get_user,
    get_sitecoordinator,
    get_site,
    get_study,
    get_funding,
    get_cardholder,
    get_deposit,
    get_manual_payment,
    get_program,
    get_escrowfunding,
    get_funding_source
)

from greenphire.web.clinclient.tests.cc_mock.base import MockTestCase
from greenphire.web.core.models import (
    TRANSACTION_CHOICES,
    TRANSACTION_DESCRIPTION_CHOICES
)
from greenphire.web.clinclient.models import Appointment
from greenphire.utils.redis_utils import get_redis_conn


class TestGPAdminFinance(MockTestCase):
    '''
    This class contains tests of the finance section of the gpadmin page.
    '''

    def populate_database(self):
        '''
        Create all the test data needed for these tests.
        '''

        random.seed(17)

        cc_mock_init()

        self.redis_ctx = get_redis_conn()

        # Create a user
        self.user = get_user(user={
            'username': 'gwashington32', 'first_name': 'George',
            'last_name': 'Washington'
        })
        self.password = 'patr1ot'
        self.user.set_password(self.password)
        self.user.save()

        # Create funding source, program, study, site_study
        self.program = get_program(
            program={
                'name': 'White House Program',
            }
        )
        self.program.greenphire_generates_1099 = True
        self.program.preauth_payment_allowed = True
        self.program.save()

        self.program.funding_source.display_programs = \
            'White House Program FS display'
        self.program.funding_source.save()

        self.study = get_study(
            study={'name': 'White House Study', 'program': self.program}
        )
        self.site = get_site(
            site={'primary_name': 'West Wing', 'user': self.user}
        )
        self.site_study = get_site_study(
            site_study={'study': self.study, 'site': self.site}
        )

        # add an address to ensure site state/country in dropdown
        address = get_address(**{
            'country': {'iso_code': 'US', 'name': 'USA'},
            'stateprovince': {'name': 'New Jersey', 'iso_code': 'NJ'},
        })
        self.program.country_list.append(address.country)

        self.site_coordinator = get_sitecoordinator(
            **{'sitecoordinator': {
                'user': self.user,
                'site': self.site
            }}
        )
        self.site_coordinator.studies.add(self.study)
        self.site_coordinator.save()

        # make the user a report viewer, etc...
        self.user.can_view_1099_reports = True
        self.user.report_programs.add(self.program)
        self.user.programs_1099.add(self.program)
        self.user.admin_programs.add(self.program)
        self.user.can_view_travel_exception_reports = True
        self.user.can_view_travel_funding_reports = True
        self.user.is_staff = True
        self.user.gp_admin = True
        self.user.save()

        self.site_coordinator = get_sitecoordinator(
            **{'sitecoordinator': {
                'user': self.user,
                'site': self.site
            }}
        )
        self.site_coordinator.studies.add(self.study)
        self.site_coordinator.save()

        # A 2nd user for the study roles
        self.second_user = get_user(user={
            'username': 'jmad44', 'first_name': 'James',
            'last_name': 'Madison'
        })
        self.second_user.set_password(self.password)
        self.second_user.admin_programs.add(self.program)
        self.second_user.save()

        self.site_coordinator2 = get_sitecoordinator(
            **{'sitecoordinator': {
                'user': self.second_user,
                'site': self.site
            }}
        )
        self.site_coordinator2.studies.add(self.study)
        self.site_coordinator2.save()

        # A 3rd user for the study roles
        self.third_user = get_user()
        self.third_user.set_password(self.password)
        self.third_user.admin_programs.add(self.program)
        self.third_user.save()

        self.site_coordinator3 = get_sitecoordinator(
            **{'sitecoordinator': {
                'user': self.third_user,
                'site': self.site
            }}
        )
        self.site_coordinator3.studies.add(self.study)
        self.site_coordinator3.save()

        # A 4th user for the study roles
        self.fourth_user = get_user()
        self.fourth_user.set_password(self.password)
        self.fourth_user.admin_programs.add(self.program)
        self.fourth_user.can_manage_users = True
        self.fourth_user.save()

        self.site_coordinator4 = get_sitecoordinator(
            **{'sitecoordinator': {
                'user': self.fourth_user,
                'site': self.site
            }}
        )
        self.site_coordinator4.studies.add(self.study)
        self.site_coordinator4.save()

        # Setup some default dates to work with
        self.eastern = pytz.timezone('US/Eastern')
        self.tz = timezone.get_current_timezone()
        self.default_date = (
            datetime.datetime.now(self.eastern) - datetime.timedelta(days=2)
        )

        # Create cardholders
        self.cardholders = [
            get_cardholder(cardholder=ch)
            for ch in [
                {
                    'first_name': 'John', 'last_name': 'Adams',
                    'site': self.site, 'user': self.user
                },
                {
                    'first_name': 'Thomas', 'last_name': 'Jefferson',
                    'site': self.site, 'user': self.user
                }
            ]
        ]

        self.deposit_totals = dict(
            [(ch.id, Decimal(0.)) for ch in self.cardholders]
        )

        get_funding(**{
            'funding': {
                'funding_source': self.program.funding_source
            }
        })
        # Make deposits to the cardholders
        for ch in self.cardholders * 5:
            amount = Decimal(500 * random.random()).quantize(Decimal('.01'))
            mp = get_manual_payment(
                manual_payment={
                    'amount': amount,
                },
                payment={
                    'payee': ch,
                    'payer': self.study,
                    'amount': amount
                }
            )
            mp.taxable = True
            mp.request_date = self.default_date
            mp.save()
            mp.payment.status = 'pending'
            mp.payment.save()

            mp.payment.approve(self.user, None)

            deposit = get_deposit(
                deposit={
                    'amount': amount,
                    'cardholder': ch,
                    'study': self.study
                }
            )

            deposit.origin = mp.payment
            deposit.created_on = self.default_date
            deposit.processed_on = self.default_date
            deposit.processed = True
            deposit.sent = True
            deposit.sent_on = self.default_date
            deposit.save()

            deposit = get_deposit(
                deposit={
                    'amount': amount + Decimal('5.00'),
                    'cardholder': ch,
                    'study': self.study
                }
            )
            deposit.origin = mp.payment
            deposit.created_on = self.default_date
            deposit.hold = True
            deposit.processing_notes = "On hold due to fund shortage"
            deposit.save()

            self.deposit_totals[ch.id] += amount
        # Make some declined payments for each Cardholder.
        self.declined_payments = []
        for ch in self.cardholders * 3:
            amount = Decimal(100 * random.random()).quantize(Decimal('.01'))
            mp = get_manual_payment(
                manual_payment={
                    'amount': amount,
                },
                payment={
                    'payee': ch,
                    'payer': self.study,
                    'amount': amount
                }
            )
            mp.taxable = True
            mp.payment.status = 'pending'
            mp.save()

            # Decline the payment.
            mp.payment.decline(self.second_user, None)
            mp.payment.status_changed_date = self.default_date
            mp.payment.request_date = self.default_date
            mp.payment.notes = 'When in the course of human Events...'
            mp.payment.save()

            self.declined_payments.append(mp.payment)

        # Make some appointments for each Cardholder.
        self.appointments = []
        for ch in self.cardholders * 2:
            appointment = Appointment(
                cardholder=ch, study=self.study, scheduled=self.default_date,
                created_by=self.user, created_on=self.default_date
            )
            appointment.save()
            self.appointments.append(appointment)

        # Add some Travel Funding transactions (escrow funding credits and
        # debits)
        self.travel_funding = []

        time_offset = datetime.timedelta(hours=0)
        time_offset_delta = datetime.timedelta(minutes=1)

        for ch in self.cardholders * 4:
            escrow_funding = get_escrowfunding(
                escrowfunding={
                    'funding_source': self.program.funding_source,
                    'transaction_amount': (
                        Decimal(50 * random.random()).quantize(Decimal('.01'))
                    ),
                    'transaction_date': self.default_date + time_offset,
                    'transaction_type': random.choice(TRANSACTION_CHOICES)[0]
                }

            )
            # Customize this EscrowFunding
            escrow_funding.transaction_description = random.choice(
                TRANSACTION_DESCRIPTION_CHOICES
            )[0]
            escrow_funding.description = 'Four score and seven years ago...'
            escrow_funding.check_number = unicode(random.randint(0, 1e8))
            escrow_funding.save()
            self.travel_funding.append(escrow_funding)

            time_offset += time_offset_delta

    def click_gpadmin_link(self, link_text, call_login=True):
        '''
        All the tests click GP ADMIN after logging in, and then some link text.
        '''
        if call_login:
            self.login(self.user.username, self.password)
        self.wait.until(EC.visibility_of_element_located(
            (By.LINK_TEXT, 'GP ADMIN')
        )).click()
        self.wait.until(
            EC.title_contains("GP Admin")
        )
        self.wait.until(EC.visibility_of_element_located(
            (By.LINK_TEXT, link_text)
        )).click()

    def test_funding_report_2(self):
        """
        Test Funding report 2.0
        """
        self.click_gpadmin_link("Funding Report 2")
        wait = WebDriverWait(self.browser, 5)
        wait.until(
            EC.visibility_of_element_located(
                (By.ID, "current_report")
            )
        )

        self.browser.find_element_by_id("btnSubmit").click()

        wait.until(
            EC.visibility_of_element_located(
                (By.ID, "report_data")
            )
        )

        rows = self.count_visible_rows("report_data")
        self.assertEqual(rows, 1)

        headers = [
            "FUNDING SOURCE (PROGRAM NAMES)",
            "FUNDING CURRENCY",
            "FUNDING ADDED",
            "ALL PENDING DISBURSEMENTS",
            "ALL ISSUED DISBURSEMENTS",
            "PENDING ACTIVITY BALANCE",
            "ISSUED ACTIVITY BALANCE",
        ]
        self.confirm_table_headers(
            expected_headers=headers,
            th_selector='#report_data thead tr.primary-header th'
        )

        self.wait.until(
            EC.text_to_be_present_in_element(
                (By.XPATH, '//table[@id="report_data"]/tbody/tr[1]/td[3]'),
                '150.00'
            )
        )
        self.wait.until(
            EC.text_to_be_present_in_element(
                (By.XPATH, '//table[@id="report_data"]/tbody/tr[1]/td[2]'),
                'USD'
            )
        )

    def test_add_issuance_funding_multi_currency(self):
        '''
        Test Add Issuance Funding with multiple currencies.
        '''
        self.click_gpadmin_link("Add Issuance Funding")

        currency_select = Select(
            self.browser.find_element_by_id('id_currency')
        )

        # Initial page load -- No funding source selected, no currency options
        self.assertEqual(len(currency_select.options), 1)
        self.assertEqual(
            currency_select.options[0].text,
            'No Available Currencies'
        )
        self.assertTrue(currency_select.options[0].is_selected())

        # Select Funding Source that has one program, with funding currency
        # USD.
        self.assertTrue(
            self.program.funding_source.programs.get().funding_currency, 'USD'
        )

        self.select_from_dropdown_by_value(
            "id_funding_source", str(self.program.funding_source.id)
        )
        sleep(2)

        currency_select = Select(
            self.browser.find_element_by_id('id_currency')
        )

        self.assertEqual(len(currency_select.options), 1)
        self.assertEqual(
            currency_select.options[0].text,
            'US Dollar'
        )
        self.assertTrue(currency_select.options[0].is_selected())

        # Test successful submit, one currency.
        self.browser.find_element_by_id('id_load_amount').send_keys('5.00')

        self.browser.find_element_by_id("add_funds").click()

        for col, value in (
            ('1', self.program.funding_source.display_programs),
            ('2', "USD"),
            ('3', "5.00"),
        ):
            self.wait.until(EC.text_to_be_present_in_element(
                (
                    By.XPATH,
                    "//table[@id='report_data']/tbody/tr[1]/td[{0}]".format(col)
                ),
                value
            ))

        # Add program with different funding currency to funding source, and
        # re-select funding source.
        program = get_program(
            program={
                'name': 'GBP program',
                'funding_source': self.program.funding_source
            }
        )
        program.funding_currency = 'GBP'
        program.save()

        self.click_gpadmin_link('Add Issuance Funding', call_login=False)
        currency_select = Select(
            self.browser.find_element_by_id('id_currency')
        )

        self.select_from_dropdown_by_value(
            "id_funding_source", str(self.program.funding_source.id)
        )
        sleep(2)

        self.assertEqual(len(currency_select.options), 3)
        self.assertEqual(
            currency_select.options[0].text,
            '--- Select a currency ---'
        )
        self.assertTrue(currency_select.options[0].is_selected())

        self.assertEqual(
            {'--- Select a currency ---', 'US Dollar', 'Pound Sterling'},
            set([x.text for x in currency_select.options])
        )

        # Try and submit without selecting a viable currency.
        self.browser.find_element_by_id("add_funds").click()

        self.assertEqual(
            self.browser.current_url,
            'http://127.0.0.1:8084/gpadmin/add_funding/'
        )
        currency_section = self.browser.find_element_by_id(
            'id_currency_section'
        )
        error_box = currency_section.find_element_by_class_name('errorlist')
        self.assertEqual(error_box.text, 'This field is required.')

        # Test successful submit, multiple currencies.
        self.select_from_dropdown_by_value('id_currency', 'GBP')
        self.browser.find_element_by_id('id_load_amount').send_keys('8.00')

        self.browser.find_element_by_id("add_funds").click()

        for col, value in (
            ('1', self.program.funding_source.display_programs),
            ('2', "GBP"),
            ('3', "8.00"),
        ):
            self.wait.until(EC.text_to_be_present_in_element(
                (
                    By.XPATH,
                    "//table[@id='report_data']/tbody/tr[1]/td[{0}]".format(col)
                ),
                value
            ))

    def test_add_edit_issuance_funding(self):
        '''
        Test Add and Edit Issuance Funding
        '''
        self.click_gpadmin_link('Add Issuance Funding')
        wait = WebDriverWait(self.browser, 5)

        self.select_from_dropdown(
            "id_funding_source",
            self.program.funding_source.display_programs
        )

        self.browser.find_element_by_id("id_load_amount").send_keys("6000.00")
        self.browser.find_element_by_id("id_check_number").send_keys("24601")

        for col, value in (
            ('1', self.program.funding_source.display_programs),
            ('3', "150.00"),
        ):
            self.wait.until(EC.text_to_be_present_in_element(
                (
                    By.XPATH,
                    "//table[@id='report_data']/tbody/tr[1]/td[{0}]".format(col)
                ),
                value
            ))

        self.browser.find_element_by_id("add_funds").click()

        self.wait.until(EC.text_to_be_present_in_element(
            (By.XPATH, "//table[@id='report_data']/tbody/tr[1]/td[3]"),
            "6,000.00"
        ))

        self.click_gpadmin_link('Edit Issuance Funding', call_login=False)

        wait.until(EC.title_contains("Edit Issuance Funding"))
        wait.until(EC.visibility_of_element_located((By.ID, "issuance_table")))

        rows = self.count_visible_rows("issuance_table")
        self.assertEqual(rows, 2)

        self.browser.find_element_by_css_selector(
            "#issuance_table_filter label input"
        ).send_keys("600")

        wait.until(
            EC.invisibility_of_element_located(
                (By.XPATH, "//tr[@id='1']/td[4]")
            )
        )

        while rows > 1:
            rows = self.count_visible_rows("issuance_table")

        self.assertEqual(rows, 1)

        td = self.browser.find_element_by_xpath(
            "//tr[@id='2']/td[4]"
        )
        actionChains = ActionChains(self.browser)
        actionChains.double_click(td).perform()

        self.browser.find_element_by_xpath(
            "//tr[@id='2']/td[4]/form/input"
        ).clear()
        self.browser.find_element_by_xpath(
            "//tr[@id='2']/td[4]/form/input"
        ).send_keys("1776")
        self.browser.find_element_by_xpath(
            "//tr[@id='2']/td[4]/form/input"
        ).send_keys(Keys.RETURN)

        self.browser.find_element_by_css_selector(
            "#issuance_table_filter label input"
        ).clear()
        self.browser.find_element_by_css_selector(
            "#issuance_table_filter label input"
        ).send_keys(Keys.RETURN)

        wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, "//tr[@id='1']/td[4]")
            )
        )

        rows = self.count_visible_rows("issuance_table")
        self.assertEqual(rows, 2)

        check_num = self.browser.find_element_by_xpath(
            "//tr[@id='2']/td[4]"
        ).text

        self.assertEqual(check_num, "1776")

    def test_issuance_funding_report(self):
        '''
        Test the Issuance Funding Report
        '''
        self.click_gpadmin_link('Issuance Funding Report')
        wait = WebDriverWait(self.browser, 5)

        wait.until(
            EC.visibility_of_element_located(
                (By.ID, "report_data")
            )
        )

        headers = [
            "FUNDING SOURCE", "FUNDING CURRENCY", "LOAD AMOUNT", "LOAD DATE",
            "CHECK/WIRE NUMBER"
        ]
        self.confirm_table_headers(headers, "report_data")

        load_amount = self.browser.find_element_by_xpath(
            "//table[@id='report_data']/tbody/tr[1]/td[3]"
        ).text

        self.assertEqual(load_amount, "150")

    def test_deposit_status_report(self):
        '''
        Test the Deposit Status Report
        '''
        self.click_gpadmin_link('Deposit Status Report')
        wait = WebDriverWait(self.browser, 5)

        self.browser.find_element_by_xpath(
            "//li[contains(text(), 'Created On')]"
        ).click()

        wait.until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, ".tool-text a[role='button']")
            )
        ).click()

        for (elem_id, send_val) in [
            ('id_filter_end_date', datetime.date.today().strftime('%d-%b-%Y')),
            ('id_filter_start_date', '01-Jan-2000')
        ]:
            elem = self.browser.find_element_by_id(elem_id)
            elem.clear()
            elem.send_keys(send_val)

        self.browser.find_element_by_css_selector(".apply-btn").click()

        headers = [
            "DATE", "TOTAL", "TOTAL COUNT", "PROCESSED", "PROCESSED COUNT",
            "PENDING", "PENDING COUNT"
        ]
        self.confirm_table_headers(headers, "report_data")
        date = self.browser.find_element_by_xpath(
            "//table[@id='report_data']/tbody/tr/td[1]"
        ).text

        self.assertEqual(self.default_date.strftime('%d-%b-%Y'), date)

        total_num = self.browser.find_element_by_xpath(
            "//table[@id='report_data']/tbody/tr/td[3]"
        ).text
        self.assertEqual("20", total_num)

        processed_num = self.browser.find_element_by_xpath(
            "//table[@id='report_data']/tbody/tr/td[5]"
        ).text
        self.assertEqual("10", processed_num)

        pending_num = self.browser.find_element_by_xpath(
            "//table[@id='report_data']/tbody/tr/td[7]"
        ).text
        self.assertEqual("10", pending_num)

    def test_deposit_report(self):
        '''
        Test the Deposit Report
        '''
        self.click_gpadmin_link('Deposit Report')
        wait = WebDriverWait(self.browser, 5)

        wait.until(
            EC.title_contains("Deposit Report")
        )

        self.browser.find_element_by_xpath(
            "//li[contains(text(), 'White House Program')]"
        ).click()

        wait.until(
            EC.presence_of_element_located(
                (By.ID, "report_data_wrapper")
            )
        )

        # this could be executing too quickly, these might already be shown
        # if so, move on.
        try:
            wait.until(
                EC.presence_of_element_located(
                    (By.ID, "report_data")
                )
            )
        except:
            return True

        headers = [
            "PROGRAM NAME", "CREATED ON", "SITE COORDINATOR", "CURRENCY",
            "AMOUNT", "CARD LAST FOUR", "SENT", "SENT ON", "PROCESSED",
            "PROCESSED ON", "ORIGIN", "STUDY"
        ]
        self.confirm_table_headers(headers)

        rows = self.count_visible_rows("report_data")
        self.assertEqual(rows, 20)

    def test_deposit_on_hold_report(self):
        '''
        Test the Deposit on Hold Report
        '''
        self.click_gpadmin_link('Deposits On Hold')
        wait = WebDriverWait(self.browser, 5)

        wait.until(
            EC.visibility_of_element_located(
                (By.ID, "data")
            )
        )

        headers = [
            "HOLD", "CREATED ON", "PK", "AMOUNT", "SUBJECT", "STUDY", "NOTES"
        ]
        self.confirm_table_headers(headers, "data")

        rows = self.count_visible_rows("data")
        self.assertEqual(rows, 10)

        for i in range(1, 10):
            note_text = self.browser.find_element_by_xpath(
                '//table[@id="data"]/tbody/tr['+str(i)+']/td[7]'
            ).text
            self.assertEquals(note_text, "On hold due to fund shortage")

    def test_manage_funding_source(self):
        '''
        Test managing funding sources
        '''
        self.click_gpadmin_link("Manage Funding Source")
        self.browser.find_element_by_id(
            "id_form-0-emails"
        ).send_keys("george.washington@usa.gov")
        self.browser.find_element_by_id(
            "id_form-0-funding_threshold"
        ).send_keys("00")
        self.browser.find_element_by_id(
            "id_form-0-payment_processing_threshold"
        ).clear()
        self.browser.find_element_by_id(
            "id_form-0-payment_processing_threshold"
        ).send_keys("100")

        self.browser.find_element_by_id("btnSubmit").click()
        # This page submit returns to you to a visually identical page with no
        # growl to confirm submission, so we're going to just sleep a moment.
        sleep(.5)
        self.click_gpadmin_link("Manage Funding Source", call_login=False)

        email = self.browser.find_element_by_id(
            "id_form-0-emails"
        ).get_attribute("value")
        funding_threshold = self.browser.find_element_by_id(
            "id_form-0-funding_threshold"
        ).get_attribute("value")
        payment_threshold = self.browser.find_element_by_id(
            "id_form-0-payment_processing_threshold"
        ).get_attribute("value")

        self.assertEqual(email, "george.washington@usa.gov")
        self.assertEqual(funding_threshold, "100000")
        self.assertEqual(payment_threshold, "100")

    def test_bank_transfer_report(self):
        '''
        Test that the bank transfer report loads
        '''
        self.click_gpadmin_link("Transfer Report")
        current_report = self.browser.find_element_by_id("current_report").text

        self.assertEqual(current_report, "Bank Transfer Report")

    def test_add_pricing_detail_and_report(self):
        '''
        Test adding pricing detail and then the report
        '''
        self.click_gpadmin_link("Add Pricing Detail")
        wait = WebDriverWait(self.browser, 5)

        wait.until(
            EC.visibility_of_element_located(
                (By.ID, "submit")
            )
        )

        self.select_from_dropdown("id_program", "White House Program")
        self.select_from_dropdown("id_pricing_types", "--New Pricing Type--")
        self.browser.find_element_by_id("id_fee_amount").send_keys("100")
        self.browser.find_element_by_id("id_new_fee").send_keys("testing name")
        self.browser.find_element_by_id("id_notes").send_keys("testing notes")
        self.browser.find_element_by_id("submit").click()
        wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, "//tr[@id='display_row_fee_1']")
            )
        )
        program = self.browser.find_element_by_xpath(
            "//tr[@id='display_row_fee_1']/td[1]"
        ).text
        amount = self.browser.find_element_by_xpath(
            "//tr[@id='display_row_fee_1']/td[2]"
        ).text
        detail = self.browser.find_element_by_xpath(
            "//tr[@id='display_row_fee_1']/td[3]"
        ).text
        notes = self.browser.find_element_by_xpath(
            "//tr[@id='display_row_fee_1']/td[4]"
        ).text

        self.assertEqual(program, "White House Program")
        self.assertEqual(amount, "100 USD")
        self.assertEqual(detail, "testing name")
        self.assertEqual(notes, "testing notes")

        self.click_gpadmin_link("Pricing Detail Report", call_login=False)

        wait.until(
            EC.presence_of_element_located(
                (By.ID, "report_form")
            )
        )

        self.select_from_dropdown("id_program", "White House Program")
        self.browser.find_element_by_id("btnSubmit").click()

        wait.until(
            EC.visibility_of_element_located(
                (By.ID, "excel_download")
            )
        )

        program = self.browser.find_element_by_xpath(
            "//table/tbody/tr[1]/td[1]"
        ).text
        amount = self.browser.find_element_by_xpath(
            "//table/tbody/tr[1]/td[4]"
        ).text
        detail = self.browser.find_element_by_xpath(
            "//table/tbody/tr[1]/td[3]"
        ).text
        notes = self.browser.find_element_by_xpath(
            "//table/tbody/tr[1]/td[5]"
        ).text

        self.assertEqual(program, "White House Program")
        self.assertEqual(amount, "100 USD")
        self.assertEqual(detail, "testing name")
        self.assertEqual(notes, "testing notes")

    def test_usage_report(self):
        '''
        Test the usage report
        '''
        self.click_gpadmin_link("Usage Report")
        wait = WebDriverWait(self.browser, 5)

        wait.until(
            EC.text_to_be_present_in_element(
                (By.CSS_SELECTOR, ".page-header h1"),
                "Usage Report"
            )
        )

        self.browser.find_element_by_id("btnSubmit").click()

        wait.until(
            EC.visibility_of_element_located(
                (By.ID, "report_data")
            )
        )

        headers = [
            "ID", "PROGRAM", "ACCOUNTING CODE", "DEPOSITS", "TRANSFER METHOD",
            "REVERSALS", "SMS IN", "SMS OUT", "EMAIL IN", "EMAIL OUT",
            "IVR IN", "IVR OUT"
        ]
        self.confirm_table_headers(headers, "report_data")

        rows = self.count_visible_rows("report_data")
        self.assertEqual(rows, 1)

        deposits = self.browser.find_element_by_xpath(
            "//table[@id='report_data']/tbody/tr[1]/td[4]"
        ).text
        self.assertEqual(deposits, "10")

        self.browser.find_element_by_id("id_start_date").clear()
        today = datetime.datetime.now(self.eastern)
        months = [
            'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
            'Oct', 'Nov', 'Dec'
        ]
        self.browser.find_element_by_id(
            "id_start_date"
        ).send_keys(
            "{day}-{mon}-{year}".format(
                day=today.day,
                mon=months[today.month],
                year=today.year
            )
        )

        self.wait_for_datepicker('report_data')

        self.browser.find_element_by_id("btnSubmit").click()

        rows = self.count_visible_rows("report_data")
        self.assertEqual(rows, 1)

        deposits = self.browser.find_element_by_xpath(
            "//table[@id='report_data']/tbody/tr[1]/td[4]"
        ).text
        self.assertEqual(deposits, "0")

    def wait_for_datepicker(self, element):
        """
        After clicking on an input, wait for datepicker
        to load, then click elsewhere to close to ensure
        other elements aren't hidden on the page.
        """
        wait = WebDriverWait(self.browser, 5)
        wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    ".datepicker.datepicker-dropdown.dropdown-menu"
                    ".datepicker-orient-left.datepicker-orient-bottom"
                )
            )
        )
        # click on "h1" to close datepicker if its showing
        self.browser.find_element_by_id(element).click()
        try:
            wait.until(
                EC.invisibility_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        ".datepicker.datepicker-dropdown.dropdown-menu"
                        ".datepicker-orient-left.datepicker-orient-bottom"
                    )
                )
            )
        except:
            # the date picker wasn't showing
            return True
