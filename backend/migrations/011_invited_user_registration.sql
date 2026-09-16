CREATE FUNCTION register_invited_user(token_hash_arg text, email_arg text, name_arg text, password_hash_arg text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v member_invites%ROWTYPE; user_id uuid; member_id uuid; tenant_slug text;
BEGIN
 SELECT * INTO v FROM member_invites WHERE token_hash=token_hash_arg AND accepted_at IS NULL AND expires_at>now() FOR UPDATE;
 IF NOT FOUND OR lower(v.email)<>lower(email_arg) THEN RETURN NULL; END IF;
 IF EXISTS(SELECT 1 FROM users WHERE tenant_id=v.tenant_id AND lower(email)=lower(email_arg)) THEN RETURN NULL; END IF;
 user_id=gen_random_uuid(); member_id=gen_random_uuid();
 INSERT INTO users(id,tenant_id,email,display_name,password_hash) VALUES(user_id,v.tenant_id,lower(email_arg),name_arg,password_hash_arg);
 INSERT INTO household_members(id,tenant_id,household_id,user_id,role,status) VALUES(member_id,v.tenant_id,v.household_id,user_id,v.role,'ACTIVE');
 UPDATE member_invites SET accepted_at=now(),version=version+1,updated_at=now() WHERE id=v.id;
 SELECT slug INTO tenant_slug FROM tenants WHERE id=v.tenant_id;
 RETURN jsonb_build_object('tenant',tenant_slug,'email',lower(email_arg));
END $$;
REVOKE ALL ON FUNCTION register_invited_user(text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION register_invited_user(text,text,text,text) TO ff_app;
