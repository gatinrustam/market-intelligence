@props(['fields'])
<dl style="display:grid;grid-template-columns:minmax(130px,1fr) 3fr;gap:0.65rem 1rem">
@foreach($fields as $key=>$value)<dt style="font-weight:600">{{ $key }}</dt><dd style="overflow-wrap:anywhere">{{ \App\Research\Display::text($value) }}</dd>@endforeach
</dl>
