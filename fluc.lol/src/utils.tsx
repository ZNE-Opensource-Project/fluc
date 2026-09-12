import type { User } from './types';
import axios from 'axios';

export function getUser(): Promise<{ user: User | null; response: any }> {
    return axios
        .get<User | null>('/api/user')
        .then((response) => {
            let data = response.data;
            if (data) {
                data.id = BigInt(data.id);
                if (data.auth) {
                    data.auth.id = BigInt(data.auth.id);
                }
            }
            return {
                user: data ?? null,
                response: response
            };
        })
        .catch((error) => {
            return {
                user: null,
                response: error
            };
        });
}

export function getAvatar(user: User): string {
    let avatar_ext = 'png';
    if (user && user.auth.avatar) {
        avatar_ext = user.auth.avatar.startsWith('a_') ? 'gif' : 'png';
    }
    if (user.auth && user.auth.avatar) {
        return `https://cdn.discordapp.com/avatars/${user.id}/${user.auth.avatar}.${avatar_ext}`
    } else {
        const index = Number((user.id >> 22n) % 6n);
        return `https://cdn.discordapp.com/embed/avatars/${index}.${avatar_ext}`
    }
}