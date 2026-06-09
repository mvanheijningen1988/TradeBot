import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  username = '';
  password = '';
  error = '';

  onLogin(): void {
    this.error = '';
    this.auth.login(this.username, this.password).subscribe({
      next: (res) => {
        if (res.must_change_password) {
          this.router.navigate(['/change-password']);
          return;
        }
        this.router.navigate(['/']);
      },
      error: () => (this.error = 'Invalid credentials.'),
    });
  }
}
