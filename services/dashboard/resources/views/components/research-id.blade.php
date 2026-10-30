@props(['value'])
<span style="font-family:monospace;overflow-wrap:anywhere">{{ $value }}</span>
<x-filament::button size="xs" color="gray" x-data="{}" x-on:click="navigator.clipboard.writeText({{ \Illuminate\Support\Js::from($value) }})">Copy ID</x-filament::button>
