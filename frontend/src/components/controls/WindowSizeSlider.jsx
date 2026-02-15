export default function WindowSizeSlider({ value, onChange }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">
        Window Size: <span className="text-slate-900 dark:text-white font-semibold">{value} days</span>
      </label>
      <input
        type="range"
        min={5}
        max={120}
        step={5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-blue-600"
      />
      <div className="flex justify-between text-[10px] text-slate-400 mt-0.5">
        <span>5</span>
        <span>30</span>
        <span>60</span>
        <span>90</span>
        <span>120</span>
      </div>
    </div>
  );
}
