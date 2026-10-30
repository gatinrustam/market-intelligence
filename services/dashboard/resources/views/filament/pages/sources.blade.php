<x-filament-panels::page>
@foreach($data['errors'] as $error)<x-research-error :message="$error" />@endforeach
<x-filament::section heading="Sources · ingestion and enrichment">
<x-research-table :headers="['Source','Source ID','Health','Last successful fetch · UTC','Documents','Enrichment state','Errors']" :rows="array_map(fn($r)=>array_values($r),$data['rows'])" />
<p style="margin-top:1rem">Partial / RSS fallback retains usable RSS evidence when full HTML cannot be fetched. Counts reflect stored enrichment results.</p>
</x-filament::section>
</x-filament-panels::page>
