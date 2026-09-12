import { Outlet } from "react-router-dom";
import Header from './../../components/Header/Header';
import type { User } from "../../types";
import Footer from "../../components/Footer/Footer";
import PresetSelector from "../../components/PresetSelector/PresetSelector";

interface Props {
    user: User | null;
    preset: number;
    setPreset: React.Dispatch<React.SetStateAction<number>>
}

export default function DashboardLayout({ preset, setPreset, user }: Props) {
    return (
        <>
            <Header user={user} />
            <PresetSelector user={user} selected_preset={preset} setPreset={setPreset} />
            <main className='content'>
                <Outlet />
            </main>
            <Footer />
        </>
    );
}
