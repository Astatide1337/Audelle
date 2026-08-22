export type ButtonVariant = 'primary' | 'surface' | 'ghost' | 'outline'
export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon-sm' | 'icon'

interface ButtonClassOptions {
  variant?: ButtonVariant
  size?: ButtonSize
  className?: string
}

export function buttonClassNames({ variant = 'primary', size = 'md', className }: ButtonClassOptions = {}) {
  return ['ui-button', `ui-button--${variant}`, `ui-button--${size}`, className].filter(Boolean).join(' ')
}
