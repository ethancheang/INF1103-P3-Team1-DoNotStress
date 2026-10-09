"""Authentication boundaries for saved student check-ins; synthetic data only."""
import unittest
from unittest.mock import patch

from main import create_app


def login_admin(client):
    client.get('/admin/login')
    with client.session_transaction() as state:
        csrf = state['csrf_token']
    response = client.post('/admin/login', data={
        'username':'admin', 'password':'DoNotStress2026!', 'csrf_token':csrf,
    })
    assert response.status_code == 302, response.status_code
    return response


class AdminAccessTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING':True, 'SECRET_KEY':'test-admin-only'})
        self.client = self.app.test_client()

    def csrf(self):
        with self.client.session_transaction() as state:
            return state['csrf_token']

    def test_student_is_default_and_navigation_hides_records(self):
        text = self.client.get('/').get_data(as_text=True)
        self.assertIn('Student view', text)
        self.assertIn('Admin sign in', text)
        self.assertNotIn('data-nav="records"', text)
        self.assertIn('"isAdmin": false', text)
        self.assertNotIn('DoNotStress2026!', text)
        self.assertNotIn('scrypt:', text)

    def test_direct_page_redirects_and_api_never_reads_records(self):
        with patch('main.data_manager.load_all_records') as load:
            response = self.client.get('/api/records?student_id=26&role=admin')
            self.assertEqual(response.status_code,401)
            self.assertNotIn('records',response.json)
            load.assert_not_called()
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertTrue(self.client.get('/records').location.endswith('/admin/login'))

    def test_login_and_logout_require_csrf(self):
        self.client.get('/admin/login')
        self.assertEqual(self.client.post('/admin/login',data={'username':'admin','password':'DoNotStress2026!'}).status_code,403)
        self.assertEqual(self.client.post('/admin/login',data={'csrf_token':'非ASCII'}).status_code,403)
        login_admin(self.client)
        self.assertEqual(self.client.post('/admin/logout').status_code,403)
        self.assertEqual(self.client.get('/admin/logout').status_code,405)
        self.assertEqual(self.client.get('/records').status_code,200)

    def test_bad_credentials_and_malformed_payloads(self):
        self.client.get('/admin/login')
        for body in ({'username':'admin','password':'wrong'}, {'username':'student','password':'DoNotStress2026!'},
                     {'username':'admin','password':['DoNotStress2026!']}, []):
            response=self.client.post('/admin/login',json=body,headers={'X-CSRF-Token':self.csrf()})
            self.assertEqual(response.status_code,401)
            self.assertEqual(self.client.get('/api/records').status_code,401)

    def test_admin_sees_records_and_new_client_stays_student(self):
        response=login_admin(self.client)
        self.assertTrue(response.location.endswith('/records'))
        text=self.client.get('/records').get_data(as_text=True)
        self.assertIn('Admin view',text)
        self.assertIn('Sign out',text)
        self.assertIn('data-nav="records"',text)
        self.assertNotIn('DoNotStress2026!',text)
        with patch('main.data_manager.load_all_records',return_value={'ok':True,'records':[]}):
            self.assertEqual(self.client.get('/api/records').status_code,200)
        self.assertEqual(self.app.test_client().get('/api/records').status_code,401)

    def test_untrusted_role_and_unknown_server_token_do_not_authorize(self):
        with self.client.session_transaction() as state:
            state['role']='admin'
            state['is_admin']=True
            state['admin_token']='invented-token'
        self.assertEqual(self.client.get('/api/records',headers={'X-Role':'admin'}).status_code,401)

    def test_logout_revokes_old_cookie_and_returns_student(self):
        login_admin(self.client)
        old_cookie=self.client.get_cookie('session').value
        response=self.client.post('/admin/logout',data={'csrf_token':self.csrf()},follow_redirects=True)
        self.assertIn('Student view',response.get_data(as_text=True))
        self.assertNotIn('data-nav="records"',response.get_data(as_text=True))
        self.assertFalse(self.app.extensions['admin_sessions'])
        self.client.set_cookie('session',old_cookie)
        self.assertEqual(self.client.get('/api/records').status_code,401)

    def test_admin_expiry(self):
        login_admin(self.client)
        with self.client.session_transaction() as state:
            token=state['admin_token']
        self.app.extensions['admin_sessions'][token]=0
        self.assertEqual(self.client.get('/api/records').status_code,401)
        self.assertTrue(self.client.get('/records').location.endswith('/admin/login'))

    def test_login_throttle_expires(self):
        self.client.get('/admin/login')
        body={'username':'admin','password':'wrong','csrf_token':self.csrf()}
        for _ in range(5):
            self.assertEqual(self.client.post('/admin/login',data=body).status_code,401)
        self.assertEqual(self.client.post('/admin/login',data=body).status_code,429)
        self.app.config['ADMIN_LOGIN_WINDOW_SECONDS']=-1
        login_admin(self.client)

    def test_password_not_echoed_or_embedded_in_static_assets(self):
        text=self.client.get('/admin/login').get_data(as_text=True)
        self.assertIn('type="password"',text)
        self.assertNotIn('DoNotStress2026!',text)
        with self.client.get('/static/campus.js') as response:
            self.assertNotIn('DoNotStress2026!',response.get_data(as_text=True))

    def test_login_rotates_csrf(self):
        self.client.get('/')
        old=self.csrf()
        login_admin(self.client)
        self.assertNotEqual(old,self.csrf())


if __name__=='__main__':
    unittest.main()
