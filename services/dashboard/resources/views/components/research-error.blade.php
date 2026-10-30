@props(['message'])
@if($message)<x-filament::section><x-filament::badge color="warning">{{ $message }}</x-filament::badge></x-filament::section>@endif
