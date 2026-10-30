<x-filament-panels::page>
<x-filament::section heading="Services · HTTP health and readiness">
<x-research-table :headers="['Service','URL','Status','Health','Ready','Latency · ms','Last checked · UTC']" :rows="array_map(fn($r)=>[$r['service'],$r['url'],$r['status'],$r['health'],$r['ready'],$r['latency_ms'],\App\Research\Display::utc($r['checked_at'])],$data['rows'])" />
<p style="margin-top:1rem">Readiness checks do not invoke Astra. Cached for 5 seconds.</p>
</x-filament::section>
</x-filament-panels::page>
