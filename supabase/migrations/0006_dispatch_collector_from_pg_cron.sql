-- Apply through the Supabase Management API (or the SQL editor).
-- GitHub drops most of collect.yml's scheduled runs: 60 a day are configured,
-- but only 9-26 a day ran in Jul-Aug 2026 and ~5 a day in September, with
-- gaps of up to five hours. pg_cron is punctual, so it now starts each run by
-- calling GitHub's workflow_dispatch API through pg_net. collect.yml keeps a
-- sparse schedule of its own as a backstop in case this stops firing.
--
-- The GitHub token (fine-grained, SoloCinema only, Actions: read and write;
-- expires 2027-09-01) lives in Vault as 'github_dispatch_token'. It's added
-- out of band so it never lands in the repo:
--   select vault.create_secret('<token>', 'github_dispatch_token');
-- and rotated with vault.update_secret(<id>, '<new token>').
--
-- Check recent calls with:
--   select status_code, created from net._http_response order by created desc;
-- (204 = dispatched; pg_net keeps responses for six hours.) Idempotent.

create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

create or replace function public.dispatch_collector()
returns bigint
language sql
security definer
set search_path = public
as $$
  select net.http_post(
    url := 'https://api.github.com/repos/DoubleJumped/SoloCinema/actions/workflows/collect.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (
        select decrypted_secret from vault.decrypted_secrets
        where name = 'github_dispatch_token'
      ),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      -- GitHub rejects API requests without a User-Agent.
      'User-Agent', 'solocinema-pg-cron'
    ),
    body := '{"ref": "main"}'::jsonb
  );
$$;

revoke all on function public.dispatch_collector() from public, anon, authenticated;

-- Every 15 min, 9:07am-11:52pm Regina time (UTC-6, no DST); pg_cron runs in
-- UTC. Same slots collect.yml used to request.
select cron.schedule(
  'solocinema-collect',
  '7,22,37,52 15-23,0-5 * * *',
  $$select public.dispatch_collector()$$
);
