import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface WalletInfo {
  id: number;
  exchange_id: number;
  quote_currency: string;
  balance: number;
  allocated: number;
  unallocated: number;
  created_at: string;
  updated_at: string;
}

export interface WalletTransaction {
  id: number;
  wallet_id: number;
  tx_type: string;
  amount: number;
  bot_id: number | null;
  description: string;
  created_at: string;
}

export interface WalletVerification {
  wallet_balance: number;
  allocated: number;
  unallocated: number;
  exchange_available: number;
  sufficient: boolean;
}

@Injectable({ providedIn: 'root' })
export class WalletService {
  private http = inject(HttpClient);
  private url = `${environment.apiUrl}/wallet`;

  getWallet(exchangeId: number): Observable<WalletInfo> {
    return this.http.get<WalletInfo>(`${this.url}/${exchangeId}`);
  }

  deposit(exchangeId: number, amount: number, quoteCurrency = 'EUR'): Observable<WalletInfo> {
    return this.http.post<WalletInfo>(`${this.url}/${exchangeId}/deposit`, {
      amount,
      quote_currency: quoteCurrency,
    });
  }

  withdraw(exchangeId: number, amount: number): Observable<WalletInfo> {
    return this.http.post<WalletInfo>(`${this.url}/${exchangeId}/withdraw`, {
      amount,
    });
  }

  getTransactions(exchangeId: number, limit = 100): Observable<WalletTransaction[]> {
    return this.http.get<WalletTransaction[]>(`${this.url}/${exchangeId}/transactions`, {
      params: { limit: limit.toString() },
    });
  }

  verify(exchangeId: number): Observable<WalletVerification> {
    return this.http.get<WalletVerification>(`${this.url}/${exchangeId}/verify`);
  }
}
