/**
 * Enhanced Form Validation Library
 * Provides comprehensive client-side validation with accessibility support
 */

import { announceToScreenReader } from './accessibility';

// Validation rule types
type ValidationRuleBase<Type extends string> = {
  type: Type;
  message: string;
};

type RequiredRule = ValidationRuleBase<'required'>;
type EmailRule = ValidationRuleBase<'email'>;
type PhoneRule = ValidationRuleBase<'phone'>;
type UrlRule = ValidationRuleBase<'url'>;
type MinLengthRule = ValidationRuleBase<'minLength'> & { value: number };
type MaxLengthRule = ValidationRuleBase<'maxLength'> & { value: number };
type PatternRule = ValidationRuleBase<'pattern'> & { value: keyof typeof ValidationPatterns };
type CustomRule = ValidationRuleBase<'custom'> & { validator: (value: unknown) => boolean };

export type ValidationRule =
  | RequiredRule
  | EmailRule
  | PhoneRule
  | UrlRule
  | MinLengthRule
  | MaxLengthRule
  | PatternRule
  | CustomRule;

export interface ValidationResult {
  isValid: boolean;
  errors: string[];
  warnings: string[];
}

export interface FieldValidationResult extends ValidationResult {
  fieldName: string;
  value: unknown;
}

export interface FormValidationResult extends ValidationResult {
  fields: Record<string, FieldValidationResult>;
  isSubmittable: boolean;
}

// Common validation patterns
export const ValidationPatterns = {
  EMAIL: /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/,
  PHONE: /^[\+]?[1-9][\d]{0,15}$/,
  URL: /^https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)$/,
  PASSWORD_STRONG: /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/,
  ALPHANUMERIC: /^[a-zA-Z0-9]+$/,
  NUMERIC: /^\d+$/,
  ALPHA: /^[a-zA-Z]+$/,
  NO_SCRIPT: /<script\b/i,
} as const;

// Form field configuration
export interface FormFieldConfig {
  name: string;
  label: string;
  type: 'text' | 'email' | 'password' | 'tel' | 'url' | 'number' | 'textarea' | 'select' | 'checkbox' | 'radio';
  rules: ValidationRule[];
  required?: boolean;
  ariaDescribedBy?: string;
  placeholder?: string;
  helpText?: string;
}

// Validation utilities
export class FormValidator {
  private fields: Map<string, FormFieldConfig> = new Map();
  private values: Map<string, unknown> = new Map();
  private errors: Map<string, string[]> = new Map();
  private touched: Set<string> = new Set();
  private submitAttempted: boolean = false;

  constructor(fields: FormFieldConfig[]) {
    fields.forEach(field => {
      this.fields.set(field.name, field);
    });
  }

  // Register field value
  setValue(fieldName: string, value: unknown): FieldValidationResult {
    this.values.set(fieldName, value);
    return this.validateField(fieldName);
  }

  // Mark field as touched
  setTouched(fieldName: string, touched: boolean = true): void {
    if (touched) {
      this.touched.add(fieldName);
    } else {
      this.touched.delete(fieldName);
    }
  }

  // Validate individual field
  validateField(fieldName: string): FieldValidationResult {
    const field = this.fields.get(fieldName);
    if (!field) {
      return {
        fieldName,
        value: undefined,
        isValid: true,
        errors: [],
        warnings: []
      };
    }

    const value = this.values.get(fieldName);
    const errors: string[] = [];
    const warnings: string[] = [];

    // Skip validation if field is not touched and form hasn't been submitted
    if (!this.touched.has(fieldName) && !this.submitAttempted) {
      return {
        fieldName,
        value,
        isValid: true,
        errors: [],
        warnings: []
      };
    }

    // Validate each rule
    for (const rule of field.rules) {
      const ruleResult = this.validateRule(value, rule);
      if (!ruleResult.isValid) {
        errors.push(rule.message);
      }
    }

    // Additional security validations
    if (typeof value === 'string') {
      // Check for potential XSS
      if (ValidationPatterns.NO_SCRIPT.test(value)) {
        errors.push('Script tags are not allowed in this field');
      }

      // Check for common injection patterns
      const injectionPatterns = [
        /javascript:/i,
        /vbscript:/i,
        /onload=/i,
        /onerror=/i,
        /onclick=/i
      ];

      if (injectionPatterns.some(pattern => pattern.test(value))) {
        errors.push('Potentially unsafe content detected');
      }
    }

    // Store errors for this field
    this.errors.set(fieldName, errors);

    const result: FieldValidationResult = {
      fieldName,
      value,
      isValid: errors.length === 0,
      errors,
      warnings
    };

    // Announce validation errors to screen readers
    if (errors.length > 0 && this.touched.has(fieldName)) {
      const errorMessage = `${field.label}: ${errors.join(', ')}`;
      announceToScreenReader(errorMessage, 'assertive');
    }

    return result;
  }

  // Validate individual rule
  private validateRule(value: unknown, rule: ValidationRule): ValidationResult {
    const stringValue = String(value ?? '').trim();
    const isEmpty = stringValue.length === 0;

    switch (rule.type) {
      case 'required':
        return {
          isValid: value !== null && value !== undefined && !isEmpty,
          errors: [],
          warnings: []
        };

      case 'email':
        return {
          isValid: isEmpty ? true : ValidationPatterns.EMAIL.test(stringValue),
          errors: [],
          warnings: []
        };

      case 'phone':
        return {
          isValid: isEmpty ? true : ValidationPatterns.PHONE.test(stringValue.replace(/\s+/g, '')),
          errors: [],
          warnings: []
        };

      case 'url':
        return {
          isValid: isEmpty ? true : ValidationPatterns.URL.test(stringValue),
          errors: [],
          warnings: []
        };

      case 'minLength':
        return {
          isValid: isEmpty ? true : stringValue.length >= rule.value,
          errors: [],
          warnings: []
        };

      case 'maxLength':
        return {
          isValid: isEmpty ? true : stringValue.length <= rule.value,
          errors: [],
          warnings: []
        };

      case 'pattern':
        const pattern = ValidationPatterns[rule.value];
        return {
          isValid: isEmpty ? true : pattern.test(stringValue),
          errors: [],
          warnings: []
        };

      case 'custom':
        return {
          isValid: rule.validator ? rule.validator(value) : true,
          errors: [],
          warnings: []
        };

      default:
        return {
          isValid: true,
          errors: [],
          warnings: []
        };
    }
  }

  // Validate entire form
  validateForm(): FormValidationResult {
    this.submitAttempted = true;
    const fieldResults: Array<[string, FieldValidationResult]> = [];
    let hasErrors = false;
    const allErrors: string[] = [];
    const allWarnings: string[] = [];

    // Validate all fields
    for (const fieldName of this.fields.keys()) {
      const result = this.validateField(fieldName);
      fieldResults.push([fieldName, result]);

      if (!result.isValid) {
        hasErrors = true;
        allErrors.push(...result.errors);
      }
      allWarnings.push(...result.warnings);
    }

    const formResult: FormValidationResult = {
      isValid: !hasErrors,
      errors: allErrors,
      warnings: allWarnings,
      fields: Object.fromEntries(fieldResults),
      isSubmittable: !hasErrors
    };

    // Announce form validation result
    if (hasErrors) {
      const errorCount = allErrors.length;
      const message = `Form validation failed with ${errorCount} error${errorCount === 1 ? '' : 's'}. Please correct the highlighted fields.`;
      announceToScreenReader(message, 'assertive');
    } else {
      announceToScreenReader('Form validation successful', 'polite');
    }

    return formResult;
  }

  // Get field errors
  getFieldErrors(fieldName: string): string[] {
    return this.errors.get(fieldName) ?? [];
  }

  // Get all errors
  getAllErrors(): Record<string, string[]> {
    const entries: Array<[string, string[]]> = [];
    for (const [fieldName, errors] of this.errors.entries()) {
      if (errors.length > 0) {
        entries.push([fieldName, errors]);
      }
    }
    return Object.fromEntries(entries);
  }

  // Check if field has errors
  hasFieldError(fieldName: string): boolean {
    const errors = this.errors.get(fieldName);
    return errors ? errors.length > 0 : false;
  }

  // Check if field is touched
  isFieldTouched(fieldName: string): boolean {
    return this.touched.has(fieldName);
  }

  // Reset validation state
  reset(): void {
    this.values.clear();
    this.errors.clear();
    this.touched.clear();
    this.submitAttempted = false;
  }

  // Get form data
  getFormData(): Record<string, unknown> {
    return Object.fromEntries(this.values.entries());
  }
}

// Utility functions for common validations
export const ValidationUtils = {
  // Create email validation rule
  email(message: string = 'Please enter a valid email address'): ValidationRule {
    return {
      type: 'email',
      message
    };
  },

  // Create required validation rule
  required(message: string = 'This field is required'): ValidationRule {
    return {
      type: 'required',
      message
    };
  },

  // Create minimum length validation rule
  minLength(length: number, message?: string): ValidationRule {
    return {
      type: 'minLength',
      value: length,
      message: message ?? `Must be at least ${length} characters long`
    };
  },

  // Create maximum length validation rule
  maxLength(length: number, message?: string): ValidationRule {
    return {
      type: 'maxLength',
      value: length,
      message: message ?? `Must be no more than ${length} characters long`
    };
  },

  // Create phone validation rule
  phone(message: string = 'Please enter a valid phone number'): ValidationRule {
    return {
      type: 'phone',
      message
    };
  },

  // Create URL validation rule
  url(message: string = 'Please enter a valid URL'): ValidationRule {
    return {
      type: 'url',
      message
    };
  },

  // Create strong password validation rule
  strongPassword(message: string = 'Password must contain at least 8 characters with uppercase, lowercase, number, and special character'): ValidationRule {
    return {
      type: 'pattern',
      value: 'PASSWORD_STRONG',
      message
    };
  },

  // Create custom validation rule
  custom(validator: (value: unknown) => boolean, message: string): ValidationRule {
    return {
      type: 'custom',
      validator,
      message
    };
  },

  // Create pattern validation rule
  pattern(pattern: keyof typeof ValidationPatterns, message: string): ValidationRule {
    return {
      type: 'pattern',
      value: pattern,
      message
    };
  }
};

// Hook for using form validation in React components
import { useState, useCallback, useMemo } from 'react';

export function useFormValidation(fields: FormFieldConfig[]) {
  const [validator] = useState(() => new FormValidator(fields));
  const [validationState, setValidationState] = useState<Map<string, FieldValidationResult>>(() => new Map());
  const [isSubmitting, setIsSubmitting] = useState(false);

  const updateField = useCallback((fieldName: string, value: unknown) => {
    const result = validator.setValue(fieldName, value);
    setValidationState((prev) => {
      const next = new Map(prev);
      next.set(fieldName, result);
      return next;
    });
    return result;
  }, [validator]);

  const touchField = useCallback((fieldName: string) => {
    validator.setTouched(fieldName, true);
    const result = validator.validateField(fieldName);
    setValidationState((prev) => {
      const next = new Map(prev);
      next.set(fieldName, result);
      return next;
    });
  }, [validator]);

  const validateAll = useCallback(() => {
    const result = validator.validateForm();
    setValidationState(new Map(Object.entries(result.fields)));
    return result;
  }, [validator]);

  const reset = useCallback(() => {
    validator.reset();
    setValidationState(new Map());
    setIsSubmitting(false);
  }, [validator]);

  const submit = useCallback(async (onSubmit: (data: Record<string, unknown>) => Promise<void>) => {
    const validation = validateAll();
    if (!validation.isSubmittable) {
      return false;
    }

    setIsSubmitting(true);
    try {
      await onSubmit(validator.getFormData());
      announceToScreenReader('Form submitted successfully', 'polite');
      return true;
    } catch (error) {
      announceToScreenReader('Form submission failed. Please try again.', 'assertive');
      throw error;
    } finally {
      setIsSubmitting(false);
    }
  }, [validateAll, validator]);

  const formState = useMemo(() => {
    const fieldList = Array.from(validationState.values());
    return {
      isValid: fieldList.every((field) => field.isValid),
      hasErrors: fieldList.some((field) => !field.isValid),
      isSubmitting,
      fields: Object.fromEntries(validationState),
    };
  }, [validationState, isSubmitting]);

  return {
    updateField,
    touchField,
    validateAll,
    reset,
    submit,
    getFieldError: (fieldName: string) => validator.getFieldErrors(fieldName),
    hasFieldError: (fieldName: string) => validator.hasFieldError(fieldName),
    isFieldTouched: (fieldName: string) => validator.isFieldTouched(fieldName),
    formState
  };
}
