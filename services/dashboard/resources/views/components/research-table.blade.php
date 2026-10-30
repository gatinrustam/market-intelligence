@props(['headers','rows'])
<div style="overflow-x:auto"><table class="fi-ta-table" style="width:100%;text-align:left">
<thead><tr>@foreach($headers as $header)<th style="padding:0.65rem">{{ $header }}</th>@endforeach</tr></thead>
<tbody>@forelse($rows as $row)<tr>@foreach($row as $cell)<td style="padding:0.65rem;vertical-align:top">{{ \App\Research\Display::text($cell) }}</td>@endforeach</tr>@empty<tr><td style="padding:0.65rem" colspan="{{ count($headers) }}">No data available</td></tr>@endforelse</tbody></table></div>
