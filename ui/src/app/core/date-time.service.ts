import { Injectable, inject } from '@angular/core';
import { AuthService } from '../services/auth.service';

type DisplayMode = 'local' | 'utc';

@Injectable({ providedIn: 'root' })
export class DateTimeService {
  private readonly auth = inject(AuthService);

  formatDateTime(value: unknown): string {
    const date = this.parseDate(value);
    if (!date) {
      return '-';
    }
    return new Intl.DateTimeFormat(this.getLocale(), {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      timeZone: this.getTimeZone(),
    }).format(date);
  }

  private parseDate(value: unknown): Date | null {
    if (!value) {
      return null;
    }
    if (value instanceof Date) {
      return Number.isNaN(value.getTime()) ? null : value;
    }

    if (typeof value !== 'string' && typeof value !== 'number') {
      return null;
    }

    const input = String(value).trim();
    if (!input) {
      return null;
    }

    const normalized = this.normalizeUtcString(input);
    const parsed = new Date(normalized);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed;
    }

    const fallback = new Date(input);
    return Number.isNaN(fallback.getTime()) ? null : fallback;
  }

  private normalizeUtcString(input: string): string {
    if (/Z$/i.test(input) || /[+-]\d\d:\d\d$/.test(input)) {
      return input;
    }
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(input)) {
      return input.replace(' ', 'T') + 'Z';
    }
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(input)) {
      return input + 'Z';
    }
    return input;
  }

  private getLocale(): string {
    const language = this.auth.currentUserValue?.language ?? 'en';
    return language === 'nl' ? 'nl-NL' : 'en-US';
  }

  private getTimeZone(): string | undefined {
    const mode = (this.auth.currentUserValue?.time_display ??
      'local') as DisplayMode;
    return mode === 'utc' ? 'UTC' : undefined;
  }
}
