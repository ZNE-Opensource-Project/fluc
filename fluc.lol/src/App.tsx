import './App.css';
import MainLayout from './layouts/MainLayout/MainLayout';
import Cookies from "universal-cookie";
import { Routes, Route, Navigate } from 'react-router-dom';
import { lazy, useEffect, useState } from 'react';
import type { User } from './types';
import { getUser } from './utils';
import PrivacyPolicy from './pages/PrivacyPolicy/PrivacyPolicy';
import TermsOfService from './pages/TermsOfService/TermsOfService';
import DashboardLayout from './layouts/DashboardLayout/DashboardLayout';
import DiscordRedirect from './pages/DiscordRedirect/DiscordRedirect';
import Faq from './pages/Faq/Faq';
import Rules from './pages/Rules/Rules';

const cookies = new Cookies();
const Dashboard = lazy(() => import('./pages/Dashboard/Dashboard'));
const Home = lazy(() => import('./pages/Home/Home'));
const Error = lazy(() => import('./pages/Error/Error'));
const Account = lazy(() => import('./pages/Account/Account'));
const ProfileSelector = lazy(() => import('./pages/ProfileSelector/ProfileSelector'));

function App() {
	const status = cookies.get('status');
	const error = cookies.get('error');
	const msg = cookies.get('msg');
	if (status || error || msg) {
		cookies.remove('error');
		cookies.remove('msg');
		cookies.remove('status');
		return <Error status={status} message={msg} error={error}></Error>
	}

	const [user, setUser] = useState<User | null>(null);
	const [preset, setPreset] = useState<number>(0);
	// const [loaded, setLoaded] = useState<boolean>(false);
	const access = cookies.get<string | undefined>('access');
	if (access) {
		useEffect(() => {
			getUser().then(({ user, response }) => {
				if (response.data?.cookies) {
					Object.entries(response.data.cookies).forEach(([name, value]) => {
						cookies.set(name, value as string, { path: '/' });
					});
				}
				if (user) {
					setUser(user);
				}
				else {
					cookies.remove('access');
					cookies.remove('user_id');
					cookies.remove('fresh_login');
				}
			});
		}, []);
	}

	// useEffect(() => {
	// 	setLoaded(!loaded);
	// 	setUser({
	// 		id: 698051706990231632n,
	// 		is_blacklisted: false,
	// 		is_owner: false,
	// 		is_super: true,
	// 		server_amount: 0,
	// 		user_amount: 0,
	// 		auth: {
	// 			access_token: 'a',
	// 			avatar: 'idk',
	// 			email: null,
	// 			id: 698051706990231632n,
	// 			refresh_token: 'kdi',
	// 			scope: 'identify guilds.join',
	// 			token_type: 'Bearer',
	// 			update_at: 9234897324,
	// 			username: 'ydel'
	// 		},
	// 		settings: null
	// 	});
	// }, []);

	return (
		<div className='app'>
			<Routes>
				<Route element={<MainLayout user={user} />}>
					<Route index element={<Home user={user} />} />
					<Route path='/account' element={<Account user={user} />} />
					<Route path='/profile-selector' element={<ProfileSelector user={user} />} />
					<Route path='/terms-of-service' element={<TermsOfService />} />
					<Route path='/privacy-policy' element={<PrivacyPolicy />} />
					<Route path='/discord' element={<DiscordRedirect />} />
					<Route path='/faq' element={<Faq />} />
					<Route path='/rules' element={<Rules />} />
					<Route path='/dash' element={<Navigate to='/dashboard' replace />} />
					<Route path='/tos' element={<Navigate to='/terms-of-service' replace />} />
					<Route path='/pp' element={<Navigate to='/privacy-policy' replace />} />
				</Route>
				<Route element={<DashboardLayout preset={preset} setPreset={setPreset} user={user} />}>
					<Route path='/dashboard' element={<Dashboard user={user} />} />
				</Route>
				<Route path='*' element={<Error status={404} message='The requested page was not found.' />} />
			</Routes >
		</div>
	)
}

export default App
