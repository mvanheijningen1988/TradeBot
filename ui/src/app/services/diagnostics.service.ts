import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface LogEntry {
  id: number;
  category: string;
  subcategory: string;
  level: string;
  message: string;
  correlation_id: string | null;
  bot_id: number | null;
  worker_id: number | null;
  timestamp: string;
}

export interface SystemStats {
  cpu_percent: number | null;
  memory_total: number | null;
  memory_available: number | null;
  memory_percent: number | null;
  platform: string;
  python: string;
}

@Injectable({ providedIn: 'root' })
export class DiagnosticsService {
  private http = inject(HttpClient);
  private url = `${environment.apiUrl}/diagnostics`;

  getStats(): Observable<SystemStats> {
    return this.http.get<SystemStats>(`${this.url}/stats`);
  }

  getLogs(params: Record<string, string | number>): Observable<LogEntry[]> {
    return this.http.get<LogEntry[]>(`${this.url}/logs`, { params: params as Record<string, string> });
  }

  setLogLevel(category: string, level: string): Observable<void> {
    return this.http.post<void>(`${this.url}/log-level`, { category, level });
  }

  removeLogLevel(category: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/log-level/${encodeURIComponent(category)}`);
  }

  getLogLevels(): Observable<Record<string, string>> {
    return this.http.get<Record<string, string>>(`${this.url}/log-levels`);
  }
}
