<?php

use App\Models\User;
use Illuminate\Support\Facades\Artisan;

Artisan::command('dashboard:bootstrap', function () {
    $email = config('dashboard.admin_email');
    $password = config('dashboard.admin_password');
    if (! $email || ! $password || strlen($password) < 16) {
        $this->error('Set DASHBOARD_ADMIN_EMAIL and a password of at least 16 characters.');

        return 1;
    }
    if (! User::where('email', $email)->exists()) {
        User::create(['name' => 'Research Admin', 'email' => $email, 'password' => $password]);
    }
    $this->info('Dashboard account available. Existing passwords were not changed.');

    return 0;
});
