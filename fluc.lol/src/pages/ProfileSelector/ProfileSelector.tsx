import { useSearchParams } from "react-router-dom";
import type { User } from "../../types"
import { getAvatar } from "../../utils";
import './ProfileSelector.css';
import { useEffect } from "react";

interface Props {
    user: User | null;
}

export default function ProfileSelector({ user }: Props) {
    const [searchParams] = useSearchParams();
    const redirect = searchParams.get('redirect');

    useEffect(() => {
        if (!user || !user.id) {
            const timeout = setTimeout(() => {
                window.location.assign(
                    `/account/login${redirect ? `?redirect=${redirect}` : ''}`
                );
            }, 300);
            return () => clearTimeout(timeout);
        }
    }, [user, redirect]);

    if (user) {
        return (
            <div>
                <a href={`account/login?${redirect ? `redirect=${redirect}&` : ''}force=True`} id='another-profile'>Select another profile</a>
                <div className='profile-card'>
                    <img src={getAvatar(user)} alt='User Icon' />
                    <a href={`${redirect || '/authorize'}?profile=${user.auth.id}`}>
                        <button>{`Continue as ${user.auth.username} `}</button>
                    </a>
                </div>
            </div>
        )
    }
}