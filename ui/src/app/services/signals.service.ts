import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface NewsSignal {
  coin: string;
  signal: string;
  score: number;
  confidence: number;
  reason: string;
  source: string;
  article_url: string;
  article_summary: string;
  timestamp: string;
  event_type: string | null;
  rsi_short?: number | null;
  rsi_long?: number | null;
  rsi_state?: string | null;
  investment_horizon?: string;
}

export interface SignalRecommendation {
  coin: string;
  signal: string;
  score: number;
  confidence: number;
  reason: string;
  source: string;
  article_url: string;
  article_summary: string;
  timestamp: string;
  rsi_short?: number | null;
  rsi_long?: number | null;
  rsi_state?: string | null;
  investment_horizon?: string;
}

export interface Recommendations {
  invest: SignalRecommendation[];
  remove: SignalRecommendation[];
}

@Injectable({ providedIn: 'root' })
export class SignalsService {
  private readonly http = inject(HttpClient);
  private readonly url = `${environment.apiUrl}/signals`;

  getLatest(limit = 50): Observable<NewsSignal[]> {
    return this.http.get<NewsSignal[]>(`${this.url}/latest`, {
      params: { limit: limit.toString() },
    });
  }

  getRecommendations(): Observable<Recommendations> {
    return this.http.get<Recommendations>(`${this.url}/recommendations`);
  }

  getByCoin(coin: string, limit = 20): Observable<NewsSignal[]> {
    return this.http.get<NewsSignal[]>(`${this.url}/coin/${coin}`, {
      params: { limit: limit.toString() },
    });
  }
}
