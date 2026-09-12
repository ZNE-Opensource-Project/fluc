import Cookies from "universal-cookie";
import type { User } from "../../types";
import Error from "../Error/Error";
import axios from "axios";
import './Account.css';

const cookies = new Cookies();
interface Props {
    user: User | null;
}

export default function Account({ user }: Props) {
    if (!user) {
        return <Error status={401} error='Unauthorized' message='Please log in to access this page.' ></Error>
    }
    function deleteAccount() {
        const confirmed = window.confirm(`Delete account associated with ${user?.auth.username} (ID: ${user?.auth.id})? This action is irreversible.`)
        if (confirmed) {
            axios.delete('/api/account').then((response) => {
                if (response.status == 200) {
                    cookies.remove('access', { path: '/' });
                    cookies.remove('user_id', { path: '/' });
                    cookies.remove('fresh_login', { path: '/' });
                    cookies.remove('theme', { path: '/' });
                }
            });
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);
        }
    }
    return (
        <>
            <h2>{`Welcome ${user.auth.username}`}</h2>
            <button onClick={deleteAccount} id='btn-delete-account'>Delete Account</button>
        </>
    )
}