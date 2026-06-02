import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, tap } from 'rxjs';
import { environment } from '../../environments/environment';

export interface User {
  id: number;
  username: string;
  role: string;
  language: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private user$ = new BehaviorSubject<User | null>(null);

  get currentUser$(): Observable<User | null> {
    return this.user$.asObservable();
  }

  isAuthenticated(): boolean {
    const token = localStorage.getItem('access_token');
    if (!token) return false;
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.exp && payload.exp * 1000 < Date.now()) {
        this.logout();
        return false;
      }
      return true;
    } catch {
      return false;
    }
  }

  login(username: string, password: string): Observable<{ access_token: string }> {
    return this.http
      .post<{ access_token: string }>(`${environment.apiUrl}/auth/login`, {
        username,
        password,
      })
      .pipe(
        tap((res) => {
          localStorage.setItem('access_token', res.access_token);
          this.loadUser();
        })
      );
  }

  logout(): void {
    localStorage.removeItem('access_token');
    this.user$.next(null);
  }

  loadUser(): void {
    this.http
      .get<User>(`${environment.apiUrl}/auth/me`)
      .subscribe({
        next: (user) => this.user$.next(user),
        error: () => this.logout(),
      });
  }
}
