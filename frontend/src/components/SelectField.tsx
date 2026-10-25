import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
  disabled?: boolean;
}

interface SelectFieldProps<T extends string> {
  label: string;
  value: T;
  options: SelectOption<T>[];
  icon: ReactNode;
  onChange: (value: T) => void;
  disabled?: boolean;
}

export function SelectField<T extends string>({
  label,
  value,
  options,
  icon,
  onChange,
  disabled = false,
}: SelectFieldProps<T>) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <span className="select-control">
        <span className="select-icon" aria-hidden="true">
          {icon}
        </span>
        <select
          value={value}
          onChange={(event) => onChange(event.target.value as T)}
          disabled={disabled}
          aria-label={label}
        >
          {options.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={option.disabled}
            >
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown className="select-chevron" size={16} aria-hidden="true" />
      </span>
    </label>
  );
}
