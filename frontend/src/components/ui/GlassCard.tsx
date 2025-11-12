import React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const glassCardVariants = cva(
  'relative overflow-hidden rounded-xl transition-all duration-300 ease-apple',
  {
    variants: {
      variant: {
        default: 'glass-card',
        strong: 'glass-card glass-card-strong',
        interactive: 'glass-card cursor-pointer hover:scale-[1.02] hover:shadow-glass-strong',
      },
      blur: {
        sm: 'backdrop-blur-sm',
        md: 'backdrop-blur-md',
        lg: 'backdrop-blur-lg',
        xl: 'backdrop-blur-xl',
      },
      padding: {
        none: 'p-0',
        sm: 'p-3',
        md: 'p-4',
        lg: 'p-6',
        xl: 'p-8',
      },
    },
    defaultVariants: {
      variant: 'default',
      blur: 'lg',
      padding: 'md',
    },
  }
);

interface GlassCardVariantProps extends VariantProps<typeof glassCardVariants> {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  'data-testid'?: string;
}

const GlassCard: React.FC<GlassCardVariantProps> = ({
  children,
  className,
  variant,
  blur,
  padding,
  onClick,
  'data-testid': testId,
  ...props
}) => {
  return (
    <div
      className={cn(glassCardVariants({ variant, blur, padding }), className)}
      onClick={onClick}
      data-testid={testId}
      {...props}
    >
      {children}
    </div>
  );
};

export default GlassCard;
