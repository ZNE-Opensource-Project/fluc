import type { User, CustomPreset } from "../../types"
import './PresetSelector.css';

interface Props {
    user: User | null;
    selected_preset: number;
    setPreset: React.Dispatch<React.SetStateAction<number>>;
}

export default function PresetSelector({ selected_preset, setPreset, user }: Props) {
    if (!user || 1) {
        return <></>;
    }
    let presets: Array<CustomPreset> = [];
    if (user.settings) {
        presets = user.settings.presets;
    }
    function newPreset() {
        const newId = presets.length + 1;
        presets.push({
            id: newId,
            preset: {
                channel: [],
                guild: [],
                role: [],
                emoji: [],
                sticker: [],
                soundboard: [],
                automod: [],
                invite: [],
                message: [],
                no_admin: [],
                template: [],
                webhook: []
            }
        });
        setPreset(newId);
    }
    return (
        <>
            <div className="preset-selector">
                {presets.map((preset) => {
                    const index = presets.indexOf(preset);
                    return <div className={`preset ${index == selected_preset && 'selected'}`}>{index}</div>;
                })}
                <div className="preset-new" onClick={newPreset}>➕ Add Preset</div>
            </div >
        </>
    )
}