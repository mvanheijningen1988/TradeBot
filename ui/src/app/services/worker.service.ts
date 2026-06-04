import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface Worker {
  id: number;
  agent_id: string;
  address: string;
  version: string;
  status: string;
  approved: boolean;
  last_heartbeat: string;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class WorkerService {
  private http = inject(HttpClient);
  private url = `${environment.apiUrl}/workers`;

  list(): Observable<Worker[]> {
    return this.http.get<Worker[]>(this.url);
  }

  approve(id: number): Observable<void> {
    return this.http.post<void>(`${this.url}/${id}/approve`, {});
  }

  reject(id: number): Observable<void> {
    return this.http.post<void>(`${this.url}/${id}/reject`, {});
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}`);
  }
}
