import { Pipe, PipeTransform, inject } from '@angular/core';
import { DateTimeService } from '../../core/date-time.service';

@Pipe({
  name: 'appDateTime',
  standalone: true,
  pure: false,
})
export class AppDateTimePipe implements PipeTransform {
  private readonly dateTime = inject(DateTimeService);

  transform(value: unknown): string {
    return this.dateTime.formatDateTime(value);
  }
}
