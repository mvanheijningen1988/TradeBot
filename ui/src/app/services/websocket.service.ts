import { Injectable, inject, NgZone } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, Subject } from 'rxjs';
import { environment } from '../../environments/environment';

@Injectable({ providedIn: 'root' })
export class WebSocketService {
  private zone = inject(NgZone);
  private router = inject(Router);
  private ws: WebSocket | null = null;
  private messages$ = new Subject<Record<string, unknown>>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  get messages(): Observable<Record<string, unknown>> {
    return this.messages$.asObservable();
  }

  connect(): void {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    const url = `${environment.wsUrl}/ws/ui?token=${token}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      this.zone.run(() => {
        try {
          this.messages$.next(JSON.parse(event.data));
        } catch {}
      });
    };

    this.ws.onclose = (event) => {
      if (event.code === 4001) {
        // Auth failure — token expired or invalid; redirect to login.
        localStorage.removeItem('access_token');
        this.zone.run(() => this.router.navigate(['/login']));
        return;
      }
      this.reconnectTimer = setTimeout(() => this.connect(), 3000);
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.ws?.close();
    this.ws = null;
  }
}
