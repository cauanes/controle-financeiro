CREATE FUNCTION accept_member_invite(token_hash_arg text, access_hash_arg text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE s auth_sessions%ROWTYPE; v member_invites%ROWTYPE; u users%ROWTYPE; member_id uuid;
BEGIN
 SELECT * INTO s FROM auth_sessions WHERE access_hash=access_hash_arg AND revoked_at IS NULL AND access_expires_at>now();
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO u FROM users WHERE id=s.user_id AND tenant_id=s.tenant_id AND status='ACTIVE';
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO v FROM member_invites WHERE token_hash=token_hash_arg AND accepted_at IS NULL AND expires_at>now() AND tenant_id=s.tenant_id AND lower(email)=lower(u.email) FOR UPDATE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF EXISTS(SELECT 1 FROM household_members WHERE tenant_id=v.tenant_id AND household_id=v.household_id AND user_id=u.id) THEN
   RETURN NULL;
 END IF;
 member_id=gen_random_uuid();
 INSERT INTO household_members(id,tenant_id,household_id,user_id,role,status) VALUES(member_id,v.tenant_id,v.household_id,u.id,v.role,'ACTIVE');
 UPDATE member_invites SET accepted_at=now(),version=version+1,updated_at=now() WHERE id=v.id;
 RETURN jsonb_build_object('id',v.household_id,'member_id',member_id);
END $$;
REVOKE ALL ON FUNCTION accept_member_invite(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION accept_member_invite(text,text) TO ff_app;
