import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { buttonClassNames, type ButtonSize, type ButtonVariant } from './buttonClassNames'

export type { ButtonSize, ButtonVariant } from './buttonClassNames'

interface ButtonClassOptions {
  variant?: ButtonVariant
  size?: ButtonSize
  className?: string
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, ButtonClassOptions {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', className, type = 'button', ...props }, ref) => (
    <button ref={ref} type={type} className={buttonClassNames({ variant, size, className })} {...props} />
  ),
)

Button.displayName = 'Button'
