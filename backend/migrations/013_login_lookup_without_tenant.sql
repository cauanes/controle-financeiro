CREATE OR REPLACE FUNCTION login_lookup(slug_arg text, email_arg text)
RETURNS TABLE(id uuid, tenant_id uuid, password_hash text)
LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT u.id, u.tenant_id, u.password_hash FROM users u JOIN tenants t ON t.id=u.tenant_id
 WHERE (slug_arg IS NULL OR slug_arg='' OR t.slug=slug_arg)
   AND u.email=email_arg
   AND u.status='ACTIVE'
   AND t.status='ACTIVE'
 ORDER BY u.created_at ASC
 LIMIT 1 $$;

GRANT EXECUTE ON FUNCTION login_lookup(text, text) TO ff_app;
