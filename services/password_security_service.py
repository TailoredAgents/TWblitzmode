"""
Password Security Service for VouchLink AI
Implements comprehensive password complexity enforcement and security policies.
"""

import re
import secrets
import string
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PasswordStrength(Enum):
    """Password strength levels."""
    VERY_WEAK = "very_weak"
    WEAK = "weak"
    FAIR = "fair"
    GOOD = "good"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


@dataclass
class PasswordPolicy:
    """Password policy configuration."""
    min_length: int = 12
    max_length: int = 128
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_numbers: bool = True
    require_symbols: bool = True
    min_unique_chars: int = 8
    max_repeated_chars: int = 2
    disallow_common_passwords: bool = True
    disallow_personal_info: bool = True
    password_history_count: int = 12
    max_age_days: int = 90
    require_2fa_for_weak: bool = True


@dataclass
class PasswordValidationResult:
    """Result of password validation."""
    is_valid: bool
    strength: PasswordStrength
    score: int  # 0-100
    issues: List[str]
    suggestions: List[str]
    estimated_crack_time: str


class PasswordSecurityService:
    """Service for password complexity enforcement and security."""

    def __init__(self, policy: Optional[PasswordPolicy] = None):
        """Initialize the password security service."""
        self.policy = policy or PasswordPolicy()
        self.common_passwords = self._load_common_passwords()
        self.weak_patterns = self._initialize_weak_patterns()

    def _load_common_passwords(self) -> set:
        """Load common passwords to disallow."""
        # Common passwords list (top 1000 most common)
        common = {
            "123456", "password", "123456789", "12345678", "12345", "1234567",
            "1234567890", "qwerty", "abc123", "111111", "123123", "admin",
            "letmein", "welcome", "monkey", "password123", "dragon", "master",
            "github", "login", "password1", "qwerty123", "root", "secret",
            "test", "user", "administrator", "guest", "default", "changeme",
            "passw0rd", "p@ssw0rd", "p@ssword", "password!", "Password123",
            "linkedin", "facebook", "google", "twitter", "instagram",
            "vouchlink", "introduce", "prospecting", "sales", "marketing"
        }
        return common

    def _initialize_weak_patterns(self) -> List[re.Pattern]:
        """Initialize patterns that indicate weak passwords."""
        return [
            re.compile(r"^(.)\1+$"),  # All same character
            re.compile(r"^(..)\1+$"),  # Repeated pairs
            re.compile(r"^(...)\1+$"),  # Repeated triplets
            re.compile(r"^12345|23456|34567|45678|56789|67890|78901|89012|90123"),  # Sequential numbers
            re.compile(r"^abcde|bcdef|cdefg|defgh|efghi|fghij|ghijk|hijkl"),  # Sequential letters
            re.compile(r"^qwert|werty|ertyu|rtyui|tyuio|yuiop"),  # Keyboard patterns
            re.compile(r"^asdfg|sdfgh|dfghj|fghjk|ghjkl"),  # Keyboard patterns
            re.compile(r"^zxcvb|xcvbn|cvbnm"),  # Keyboard patterns
        ]

    def validate_password(self, password: str, user_info: Optional[Dict[str, str]] = None) -> PasswordValidationResult:
        """Validate a password against the security policy."""
        issues = []
        suggestions = []
        score = 0

        # Basic length check
        if len(password) < self.policy.min_length:
            issues.append(f"Password must be at least {self.policy.min_length} characters long")
            suggestions.append(f"Add {self.policy.min_length - len(password)} more characters")

        if len(password) > self.policy.max_length:
            issues.append(f"Password must be no more than {self.policy.max_length} characters long")

        # Character complexity checks
        has_uppercase = bool(re.search(r'[A-Z]', password))
        has_lowercase = bool(re.search(r'[a-z]', password))
        has_numbers = bool(re.search(r'[0-9]', password))
        has_symbols = bool(re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?~`]', password))

        if self.policy.require_uppercase and not has_uppercase:
            issues.append("Password must contain at least one uppercase letter")
            suggestions.append("Add an uppercase letter (A-Z)")

        if self.policy.require_lowercase and not has_lowercase:
            issues.append("Password must contain at least one lowercase letter")
            suggestions.append("Add a lowercase letter (a-z)")

        if self.policy.require_numbers and not has_numbers:
            issues.append("Password must contain at least one number")
            suggestions.append("Add a number (0-9)")

        if self.policy.require_symbols and not has_symbols:
            issues.append("Password must contain at least one special character")
            suggestions.append("Add a special character (!@#$%^&* etc.)")

        # Unique character count
        unique_chars = len(set(password.lower()))
        if unique_chars < self.policy.min_unique_chars:
            issues.append(f"Password must contain at least {self.policy.min_unique_chars} unique characters")
            suggestions.append(f"Add {self.policy.min_unique_chars - unique_chars} more unique characters")

        # Repeated character check
        max_repeated = self._get_max_repeated_chars(password)
        if max_repeated > self.policy.max_repeated_chars:
            issues.append(f"Password contains too many repeated characters (max {self.policy.max_repeated_chars})")
            suggestions.append("Reduce repeated characters")

        # Common password check
        if self.policy.disallow_common_passwords and password.lower() in self.common_passwords:
            issues.append("Password is too common and easily guessable")
            suggestions.append("Choose a more unique password")

        # Weak pattern check
        for pattern in self.weak_patterns:
            if pattern.search(password.lower()):
                issues.append("Password contains predictable patterns")
                suggestions.append("Avoid keyboard patterns and sequences")
                break

        # Personal information check
        if self.policy.disallow_personal_info and user_info:
            personal_issues = self._check_personal_info(password, user_info)
            issues.extend(personal_issues)
            if personal_issues:
                suggestions.append("Avoid using personal information in passwords")

        # Calculate score and strength
        score = self._calculate_password_score(password)
        strength = self._determine_strength(score, len(issues))
        crack_time = self._estimate_crack_time(password, score)

        # Add suggestions based on strength
        if strength in [PasswordStrength.VERY_WEAK, PasswordStrength.WEAK]:
            suggestions.append("Consider using a passphrase (4+ random words)")
            suggestions.append("Use a password manager to generate strong passwords")

        return PasswordValidationResult(
            is_valid=len(issues) == 0,
            strength=strength,
            score=score,
            issues=issues,
            suggestions=suggestions,
            estimated_crack_time=crack_time
        )

    def _get_max_repeated_chars(self, password: str) -> int:
        """Get the maximum number of consecutive repeated characters."""
        if not password:
            return 0

        max_count = 1
        current_count = 1

        for i in range(1, len(password)):
            if password[i].lower() == password[i-1].lower():
                current_count += 1
                max_count = max(max_count, current_count)
            else:
                current_count = 1

        return max_count

    def _check_personal_info(self, password: str, user_info: Dict[str, str]) -> List[str]:
        """Check if password contains personal information."""
        issues = []
        password_lower = password.lower()

        personal_fields = ['first_name', 'last_name', 'email', 'company', 'username']

        for field in personal_fields:
            if field in user_info and user_info[field]:
                value = user_info[field].lower()
                if len(value) >= 3 and value in password_lower:
                    issues.append(f"Password contains personal information ({field})")
                    break

        # Check email domain
        if 'email' in user_info and '@' in user_info['email']:
            domain = user_info['email'].split('@')[1].lower()
            if domain in password_lower:
                issues.append("Password contains email domain")

        return issues

    def _calculate_password_score(self, password: str) -> int:
        """Calculate password strength score (0-100)."""
        score = 0

        # Length score (up to 25 points)
        score += min(25, len(password) * 2)

        # Character variety score (up to 25 points)
        variety_score = 0
        if re.search(r'[a-z]', password):
            variety_score += 5
        if re.search(r'[A-Z]', password):
            variety_score += 5
        if re.search(r'[0-9]', password):
            variety_score += 5
        if re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?~`]', password):
            variety_score += 10

        score += variety_score

        # Unique character score (up to 20 points)
        unique_ratio = len(set(password)) / len(password) if password else 0
        score += int(unique_ratio * 20)

        # Entropy score (up to 30 points)
        entropy = self._calculate_entropy(password)
        score += min(30, int(entropy / 3))

        # Penalty for common patterns
        for pattern in self.weak_patterns:
            if pattern.search(password.lower()):
                score -= 15
                break

        # Penalty for common passwords
        if password.lower() in self.common_passwords:
            score -= 25

        return max(0, min(100, score))

    def _calculate_entropy(self, password: str) -> float:
        """Calculate password entropy in bits."""
        if not password:
            return 0

        # Character set size
        charset_size = 0
        if re.search(r'[a-z]', password):
            charset_size += 26
        if re.search(r'[A-Z]', password):
            charset_size += 26
        if re.search(r'[0-9]', password):
            charset_size += 10
        if re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?~`]', password):
            charset_size += 32

        # Shannon entropy approximation
        import math
        if charset_size > 0:
            return len(password) * math.log2(charset_size)
        return 0

    def _determine_strength(self, score: int, issue_count: int) -> PasswordStrength:
        """Determine password strength based on score and issues."""
        if issue_count > 3 or score < 30:
            return PasswordStrength.VERY_WEAK
        elif issue_count > 1 or score < 50:
            return PasswordStrength.WEAK
        elif issue_count > 0 or score < 65:
            return PasswordStrength.FAIR
        elif score < 80:
            return PasswordStrength.GOOD
        elif score < 90:
            return PasswordStrength.STRONG
        else:
            return PasswordStrength.VERY_STRONG

    def _estimate_crack_time(self, password: str, score: int) -> str:
        """Estimate time to crack password."""
        if score < 30:
            return "Instantly"
        elif score < 50:
            return "Minutes"
        elif score < 65:
            return "Hours"
        elif score < 80:
            return "Days"
        elif score < 90:
            return "Months"
        else:
            return "Centuries"

    def generate_secure_password(self, length: int = 16, use_symbols: bool = True) -> str:
        """Generate a cryptographically secure password."""
        if length < self.policy.min_length:
            length = self.policy.min_length

        # Character sets
        lowercase = string.ascii_lowercase
        uppercase = string.ascii_uppercase
        digits = string.digits
        symbols = "!@#$%^&*()_+-=[]{}|;:,.<>?"

        # Ensure at least one character from each required set
        password_chars = []

        if self.policy.require_lowercase:
            password_chars.append(secrets.choice(lowercase))

        if self.policy.require_uppercase:
            password_chars.append(secrets.choice(uppercase))

        if self.policy.require_numbers:
            password_chars.append(secrets.choice(digits))

        if self.policy.require_symbols and use_symbols:
            password_chars.append(secrets.choice(symbols))

        # Build character set for remaining characters
        charset = lowercase
        if self.policy.require_uppercase:
            charset += uppercase
        if self.policy.require_numbers:
            charset += digits
        if self.policy.require_symbols and use_symbols:
            charset += symbols

        # Fill remaining length
        for _ in range(length - len(password_chars)):
            password_chars.append(secrets.choice(charset))

        # Shuffle the password
        secrets.SystemRandom().shuffle(password_chars)

        return ''.join(password_chars)

    def generate_passphrase(self, word_count: int = 4, separator: str = "-") -> str:
        """Generate a secure passphrase using random words."""
        # Simple word list for passphrase generation
        words = [
            "apple", "bridge", "cloud", "dance", "energy", "forest", "guitar", "happy",
            "island", "jungle", "kite", "light", "mountain", "nature", "ocean", "peace",
            "quiet", "river", "sunset", "tree", "unity", "valley", "water", "yellow",
            "zebra", "adventure", "brave", "creative", "dream", "explore", "freedom",
            "gentle", "harmony", "inspire", "journey", "kindness", "laughter", "magic",
            "noble", "optimism", "passion", "quest", "radiant", "serenity", "triumph",
            "unique", "vibrant", "wisdom", "wonder", "courage", "delight", "elegant",
            "fantastic", "graceful", "brilliant", "majestic", "powerful", "splendid"
        ]

        selected_words = [secrets.choice(words) for _ in range(word_count)]

        # Capitalize first letter of each word and add numbers
        processed_words = []
        for word in selected_words:
            processed_word = word.capitalize()
            # Randomly add a number to some words
            if secrets.choice([True, False]):
                processed_word += str(secrets.randbelow(100))
            processed_words.append(processed_word)

        passphrase = separator.join(processed_words)

        # Add a special character at the end if required
        if self.policy.require_symbols:
            passphrase += secrets.choice("!@#$%^&*")

        return passphrase

    def check_password_age(self, password_created: datetime) -> Dict[str, Any]:
        """Check if password needs to be changed based on age."""
        age = datetime.now(timezone.utc) - password_created
        max_age = timedelta(days=self.policy.max_age_days)

        return {
            "age_days": age.days,
            "max_age_days": self.policy.max_age_days,
            "needs_change": age > max_age,
            "expires_in_days": max(0, self.policy.max_age_days - age.days)
        }

    def hash_password(self, password: str, salt: Optional[str] = None) -> Tuple[str, str]:
        """Hash a password using PBKDF2 with SHA-256."""
        if salt is None:
            salt = secrets.token_hex(32)

        # Use PBKDF2 with 100,000 iterations (recommended by OWASP)
        import hashlib
        import base64

        key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        hashed = base64.b64encode(key).decode('utf-8')

        return f"{salt}${hashed}", salt

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        try:
            salt, stored_hash = hashed_password.split('$', 1)
            computed_hash, _ = self.hash_password(password, salt)
            return computed_hash == hashed_password
        except ValueError:
            return False


# Global instance with default policy
password_security_service = PasswordSecurityService()


def validate_password_strength(password: str, user_info: Optional[Dict[str, str]] = None) -> PasswordValidationResult:
    """Convenience function to validate password strength."""
    return password_security_service.validate_password(password, user_info)


def generate_secure_password(length: int = 16) -> str:
    """Convenience function to generate a secure password."""
    return password_security_service.generate_secure_password(length)